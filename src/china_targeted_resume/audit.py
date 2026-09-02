"""Deterministic ATS, human, technical, truth, and privacy audits."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence

from china_targeted_resume.composition import (
    contains_placeholder,
    evidence_is_allowed,
    fact_ledger_ref,
    provenance_ref,
    render_ats_text,
    resume_labels,
    resume_claim_is_substantive,
)
from china_targeted_resume.models import ResumeVariant, ValidationReport
_BLOCKED_FACT_STATES = frozenset({"F4", "F5", "F6"})
_PRIVATE_DISCLOSURES = frozenset({"P3"})
_SECRET = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd|private[_-]?key)\s*[:=]\s*\S+")
_INTERNAL_URL = re.compile(r"(?i)(?:file|ssh)://|https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|[^/\s]+\.(?:internal|local))(?:[/:]|\b)")
_PRIVATE_LOG = re.compile(r"(?i)(?:private|internal|customer)[-_ /]?(?:log|repo|repository|trace)s?\b|(?:^|[/\\])(?:logs?|\.git)(?:[/\\]|$)")
_METRIC = re.compile(r"(?<!\w)(?:~|≈|about|approximately|roughly|nearly|more than|less than)?\s*\d+(?:[.,]\d+)?\s*(?:%|ms|s|sec(?:onds?)?|minutes?|hours?|days?|x|倍|万|亿|个|人|台|次|条|项)?", re.I)
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")


@dataclass(frozen=True)
class _Finding:
    category: str
    code: str
    message: str
    error: bool = True

    @property
    def actionable(self) -> str:
        level = "ERROR" if self.error else "WARNING"
        return f"[{level}][{self.category}.{self.code}] {self.message}"


def _plain(value: Any) -> Any:
    return value.model_dump(mode="python") if hasattr(value, "model_dump") else value


def _dict(value: Any) -> dict[str, Any]:
    value = _plain(value)
    return dict(value) if isinstance(value, Mapping) else {}


def _get(value: Any, *names: str, default: Any = None) -> Any:
    data = _dict(value)
    for name in names:
        if name in data and data[name] is not None:
            result = data[name]
            return result.value if hasattr(result, "value") else result
    return default


def _items(value: Any) -> list[Any]:
    value = _plain(value)
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    return list(value) if isinstance(value, Iterable) else [value]


def _mode(mode: Any, document: Any) -> str:
    value = getattr(mode, "value", mode)
    if value:
        return str(value)
    return str(_get(document, "mode", default="targeted_application"))


def _bullets(document: Any) -> list[tuple[str, int, Any]]:
    result = []
    for section in ("experience", "projects"):
        for container_index, container in enumerate(_items(_get(document, section, default=[]))):
            for bullet in _items(_get(container, "bullets", default=[])):
                result.append((section, container_index, bullet))
    return result


def _visible_text(document: Any) -> str:
    """Text users/ATS see; intentionally excludes internal provenance paths."""
    try:
        return render_ats_text(document)
    except ValueError:
        data = _dict(document)
        parts = [str(data.get("headline") or "")]
        parts.extend(str(value) for value in _dict(data.get("contact", {})).values() if isinstance(value, str))
        parts.extend(str(_get(bullet, "text", default="")) for _, _, bullet in _bullets(document))
        return "\n".join(parts)
def _fact_prefix(text: Any) -> str:
    import hashlib
    digest = hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()[:20]
    return f"fact:{digest}:"


def _visible_facts(document: Any) -> list[tuple[str, str]]:
    """Enumerate the same non-structural facts emitted by both text renderers."""
    data = _dict(document); facts: list[tuple[str, str]] = []
    selected_evidence_label = resume_labels(data.get("locale"))["selected_evidence"]
    contact = _dict(data.get("contact", {}))
    for key in ("name", "phone", "email", "location"):
        if contact.get(key): facts.append((f"contact.{key}", str(contact[key])))
    for index, link in enumerate(_items(contact.get("links"))):
        for key in ("label", "url"):
            value = _get(link, key, default="")
            if value: facts.append((f"links[{index + 1}].{key}", str(value)))
    if data.get("headline"): facts.append(("headline", str(data["headline"])))
    facts.extend((f"summary[{index + 1}]", str(value)) for index, value in enumerate(_items(data.get("summary"))))
    for group_index, group in enumerate(_items(data.get("skills"))):
        name = _get(group, "group", default="")
        if name: facts.append((f"skills[{group_index + 1}].group", str(name)))
        facts.extend((f"skills[{group_index + 1}].items[{index + 1}]", str(value)) for index, value in enumerate(_items(_get(group, "items", default=[]))))
    for section in ("experience", "projects"):
        for index, item in enumerate(_items(data.get(section))):
            for key in ("organization", "name", "role", "location", "start_date", "end_date", "context"):
                value = _get(item, key, default="")
                if value and not (
                    key == "name" and value == selected_evidence_label
                ):
                    facts.append((f"{section}[{index + 1}].{key}", str(value)))
            facts.extend((f"{section}[{index + 1}].technologies[{tech_index + 1}]", str(value)) for tech_index, value in enumerate(_items(_get(item, "technologies", default=[]))))
            facts.extend((f"{section}[{index + 1}].bullets[{bullet_index + 1}]", str(_get(bullet, "text", default=""))) for bullet_index, bullet in enumerate(_items(_get(item, "bullets", default=[]))) if _get(bullet, "text", default=""))
    for section in ("education", "honors"):
        for index, item in enumerate(_items(data.get(section))):
            for key in ("institution", "name", "degree", "field", "issuer", "date", "start_date", "end_date", "details"):
                for value_index, value in enumerate(_items(_get(item, key, default=[]))):
                    if value: facts.append((f"{section}[{index + 1}].{key}[{value_index + 1}]", str(value)))
    return facts


def _report(category: str, findings: Sequence[_Finding], checks: Mapping[str, bool] | None = None) -> ValidationReport:
    errors = [finding.actionable for finding in findings if finding.error]
    warnings = [finding.actionable for finding in findings if not finding.error]
    return ValidationReport(success=not errors, checks=dict(checks or {}), errors=errors, warnings=warnings, details={"category": category, "finding_count": len(findings)})


def _narrative_fields(document: Any) -> list[tuple[str, str]]:
    data = _dict(document)
    fields: list[tuple[str, str]] = []
    if data.get("headline"):
        fields.append(("headline", str(data["headline"])))
    fields.extend(
        (f"summary[{index + 1}]", str(value))
        for index, value in enumerate(_items(data.get("summary")))
        if str(value).strip()
    )
    for section in ("experience", "projects"):
        for index, item in enumerate(_items(data.get(section))):
            context = str(_get(item, "context", default="") or "").strip()
            if context:
                fields.append((f"{section}[{index + 1}].context", context))
            fields.extend(
                (
                    f"{section}[{index + 1}].bullets[{bullet_index + 1}]",
                    str(_get(bullet, "text", default="")),
                )
                for bullet_index, bullet in enumerate(
                    _items(_get(item, "bullets", default=[]))
                )
                if str(_get(bullet, "text", default="")).strip()
            )
    for section in ("education", "honors"):
        for index, item in enumerate(_items(data.get(section))):
            fields.extend(
                (f"{section}[{index + 1}].details[{detail_index + 1}]", str(value))
                for detail_index, value in enumerate(
                    _items(_get(item, "details", default=[]))
                )
                if str(value).strip()
            )
    return fields


def _language_mismatches(document: Any) -> list[str]:
    locale = str(_get(document, "locale", default="") or "").casefold()
    if not locale.startswith("zh"):
        return []
    return [
        path
        for path, text in _narrative_fields(document)
        if not _CJK.search(text) and len(_ENGLISH_WORD.findall(text)) >= 3
    ]


def _ats_findings(document: Any, requirements: Sequence[Any]) -> tuple[list[_Finding], dict[str, bool]]:
    findings: list[_Finding] = []
    data = _dict(document); contact = _dict(data.get("contact", {}))
    if not contact.get("name"):
        findings.append(_Finding("ats", "missing_name", "Add the candidate name to the contact block."))
    if not str(data.get("headline") or "").strip():
        findings.append(_Finding("ats", "missing_headline", "Add a concise target-direction headline."))
    text = _visible_text(document)
    if contains_placeholder(text):
        findings.append(_Finding("ats", "placeholder", "Remove every unresolved placeholder before rendering."))
    standard_sections = all(isinstance(data.get(name, []), list) for name in ("summary", "skills", "experience", "projects", "education", "honors"))
    if not standard_sections:
        findings.append(_Finding("ats", "section_shape", "Use standard list-based resume sections in canonical order."))
    language_mismatches = _language_mismatches(document)
    for path in language_mismatches:
        findings.append(
            _Finding(
                "ats",
                "language_mismatch",
                f"Translate English-only narrative field {path} for the requested zh-CN resume without changing its evidence boundary.",
            )
        )
    evidence_text = " ".join(str(_get(bullet, "text", default="")) for _, _, bullet in _bullets(document)).casefold()
    for group_index, group in enumerate(_items(data.get("skills", []))):
        for skill in _items(_get(group, "items", default=[])):
            if str(skill).casefold() not in evidence_text:
                findings.append(_Finding("ats", "unsupported_skill", f"Remove or evidence skill {skill!r} in skill group {group_index + 1}."))
    required_keywords = []
    for requirement in requirements:
        if str(_get(requirement, "priority", default="")).lower() in {"critical", "high"}:
            required_keywords.extend(str(value) for value in _items(_get(requirement, "keywords", default=[])))
    missing = sorted({keyword for keyword in required_keywords if keyword and keyword.casefold() not in text.casefold()}, key=str.casefold)
    if missing:
        findings.append(_Finding("ats", "keyword_coverage", "Review natural coverage for high-priority keywords: " + ", ".join(missing), error=False))
    checks = {
        "single_column_model": True,
        "canonical_section_order": standard_sections,
        "no_image_only_text": True,
        "no_placeholders": not contains_placeholder(text),
        "locale_consistent_narrative": not language_mismatches,
    }
    return findings, checks


def audit_ats(document: Any, requirements: Sequence[Any] = ()) -> ValidationReport:
    findings, checks = _ats_findings(document, requirements)
    return _report("ats", findings, checks)


def _hr_findings(document: Any) -> tuple[list[_Finding], dict[str, bool]]:
    findings: list[_Finding] = []
    data = _dict(document)
    headline = bool(str(data.get("headline") or "").strip())
    if not headline:
        findings.append(_Finding("hr", "direction", "Make the target direction identifiable in the headline."))
    bullets = _bullets(document)
    target_pages = int(_get(_get(document, "render_policy", default={}), "target_pages", default=2))
    minimum_bullets, maximum_bullets = (
        target_pages * 6,
        target_pages * 10,
    )
    if len(bullets) < minimum_bullets:
        findings.append(_Finding(
            "hr",
            "density_underfill",
            (
                f"Add verified, relevant outcomes when available; the "
                f"{target_pages}-page profile targets at least "
                f"{minimum_bullets} visible bullets."
            ),
            error=False,
        ))
    if len(bullets) > maximum_bullets:
        findings.append(_Finding("hr", "density", f"Reduce visible bullets to at most {maximum_bullets}; retain the most relevant verified outcomes.", error=False))
    for index, experience in enumerate(_items(data.get("experience", []))):
        required = ("organization", "role", "start_date", "end_date")
        missing = [field for field in required if not str(_get(experience, field, default="")).strip()]
        if missing:
            findings.append(_Finding("hr", "timeline", f"Experience {index + 1} needs explicit {', '.join(missing)}; do not disguise timeline gaps."))
    checks = {
        "target_direction_visible": headline,
        "core_outcome_visible": bool(bullets),
        "sufficient_density": len(bullets) >= minimum_bullets,
        "reasonable_density": len(bullets) <= maximum_bullets,
    }
    return findings, checks


def audit_hr(document: Any) -> ValidationReport:
    findings, checks = _hr_findings(document)
    return _report("hr", findings, checks)


def _technical_findings(document: Any, evidence_records: Sequence[Any]) -> tuple[list[_Finding], dict[str, bool]]:
    findings: list[_Finding] = []
    records = {str(_get(record, "evidence_id", default="")): record for record in evidence_records}
    if _get(document, "variant") != ResumeVariant.RECRUITER_ONE_PAGE.value:
        for index, project in enumerate(
            _items(_get(document, "projects", default=[]))
        ):
            if not str(_get(project, "context", default="")).strip():
                findings.append(
                    _Finding(
                        "technical",
                        "project_context",
                        (
                            "Add a source-backed system/problem context to "
                            f"project {index + 1}."
                        ),
                        error=False,
                    )
                )
    for section, index, bullet in _bullets(document):
        claim_ids = [str(value) for value in _items(_get(bullet, "claim_ids", default=[]))]
        text = str(_get(bullet, "text", default=""))
        for claim_id in claim_ids:
            record = records.get(claim_id)
            if record is None:
                continue
            scope = str(_get(record, "contribution_scope", default="")).strip()
            if not scope:
                findings.append(_Finding("technical", "contribution_scope", f"Document personal-versus-team contribution for claim {claim_id}."))
            safe_claim = str(_get(record, "safe_claim", default=""))
            if _METRIC.search(text) and text != safe_claim:
                findings.append(_Finding("technical", "metric_scope", f"Restore the exact qualified metric wording for claim {claim_id}."))
            if not resume_claim_is_substantive(record, text=text):
                findings.append(_Finding(
                    "technical",
                    "resume_readiness",
                    (
                        f"Remove audit, metadata, boundary, or standalone-intro "
                        f"claim {claim_id} from visible resume sections."
                    ),
                ))
    checks = {
        "contribution_boundaries": not any(
            finding.code == "contribution_scope" for finding in findings
        ),
        "metric_wording_preserved": not any(
            finding.code == "metric_scope" for finding in findings
        ),
        "visible_claims_substantive": not any(
            finding.code == "resume_readiness" for finding in findings
        ),
    }
    return findings, checks


def audit_technical(document: Any, evidence_records: Sequence[Any] = ()) -> ValidationReport:
    findings, checks = _technical_findings(document, evidence_records)
    return _report("technical", findings, checks)


def _truth_findings(document: Any, evidence_records: Sequence[Any], provenance_records: Sequence[Any], mode: str) -> tuple[list[_Finding], dict[str, bool]]:
    findings: list[_Finding] = []
    records = {str(_get(record, "evidence_id", default="")): record for record in evidence_records}
    provenance = {str(_get(record, "claim_id", default="")): record for record in provenance_records}
    document_refs = {str(value) for value in _items(_get(document, "provenance_refs", default=[]))}
    for section, index, bullet in _bullets(document):
        claim_ids = [str(value) for value in _items(_get(bullet, "claim_ids", default=[]))]
        bullet_refs = [str(value) for value in _items(_get(bullet, "provenance_refs", default=[]))]
        location = f"{section}[{index + 1}]"
        if not claim_ids:
            findings.append(_Finding("truth", "missing_claim_id", f"Attach a claim_id to every bullet in {location}."))
            continue
        text = str(_get(bullet, "text", default=""))
        matched_text = False
        for claim_id in claim_ids:
            record = records.get(claim_id)
            if record is None:
                findings.append(_Finding("truth", "unknown_claim", f"Remove or resolve unknown claim_id {claim_id} in {location}."))
                continue
            if text == str(_get(record, "safe_claim", default="")):
                matched_text = True
            fact = str(_get(record, "fact_state", default="")); disclosure = str(_get(record, "disclosure", default=""))
            if fact in _BLOCKED_FACT_STATES:
                findings.append(_Finding("truth", "blocked_fact", f"Remove claim {claim_id}; fact state {fact} is not publishable."))
            if disclosure in _PRIVATE_DISCLOSURES or (disclosure == "P2" and mode != "targeted_application"):
                findings.append(_Finding("truth", "disclosure", f"Remove claim {claim_id}; disclosure {disclosure} is not allowed in {mode}."))
            ref = provenance_ref(record)
            expected_ledger = fact_ledger_ref(text, ref) if ref else None
            if not ref or ref not in document_refs or expected_ledger not in document_refs or (bullet_refs and ref not in bullet_refs):
                findings.append(_Finding("truth", "provenance_coverage", f"Add the exact source reference and fact ledger entry for claim {claim_id}."))
            source_path = str(_get(_get(record, "source", default={}), "path", default="")).replace("\\", "/").lower()
            if "company-research/" in source_path:
                findings.append(_Finding("truth", "company_research_fact", f"Remove claim {claim_id}; company research cannot evidence a personal fact."))
            p_record = provenance.get(claim_id)
            if p_record is not None and str(_get(p_record, "rendered_claim", default="")) != text:
                findings.append(_Finding("truth", "provenance_text", f"Make provenance rendered_claim exactly match visible claim {claim_id}."))
        if not matched_text:
            findings.append(_Finding("truth", "claim_expansion", f"Restore the unchanged safe_claim text for bullet in {location}; do not strengthen verbs or metrics."))
    for summary_index, summary in enumerate(_items(_get(document, "summary", default=[]))):
        matches = [record for record in records.values() if str(_get(record, "safe_claim", default="")) == str(summary)]
        allowed_matches = [record for record in matches if evidence_is_allowed(record, mode)]
        allowed_matches = [record for record in allowed_matches if "company-research/" not in str(_get(_get(record, "source", default={}), "path", default="")).replace("\\", "/").lower()]
        traceable_matches = [record for record in allowed_matches if (ref := provenance_ref(record)) in document_refs and fact_ledger_ref(summary, ref) in document_refs]
        if not traceable_matches:
            findings.append(_Finding("truth", "summary_provenance", f"Remove or replace summary line {summary_index + 1}; it lacks allowed, non-company-research evidence and exact provenance."))
    visible_facts = _visible_facts(document)
    for location, text in visible_facts:
        if not any(ref.startswith(_fact_prefix(text)) for ref in document_refs):
            findings.append(_Finding("truth", "visible_fact_provenance", f"Add a fact-to-source ledger entry for visible field {location}."))
    company_refs = [ref for ref in document_refs if "company-research/" in ref.replace("\\", "/").lower()]
    for location, text in visible_facts:
        if any(fact_ledger_ref(text, ref) in document_refs for ref in company_refs):
            findings.append(_Finding("truth", "company_research_fact", f"Replace company research as personal evidence for visible field {location}."))
    checks = {
        "every_bullet_has_claim_id": not any(f.code == "missing_claim_id" for f in findings),
        "every_visible_fact_has_provenance": not any(f.code in {"provenance_coverage", "visible_fact_provenance"} for f in findings),
        "safe_claim_unchanged": not any(f.code == "claim_expansion" for f in findings),
        "blocked_states_absent": not any(f.code in {"blocked_fact", "disclosure"} for f in findings),
        "company_research_not_personal_evidence": not any(f.code == "company_research_fact" for f in findings),
    }
    return findings, checks


def audit_truth(document: Any, evidence_records: Sequence[Any] = (), provenance_records: Sequence[Any] = (), *, mode: Any = None) -> ValidationReport:
    findings, checks = _truth_findings(document, evidence_records, provenance_records, _mode(mode, document))
    return _report("truth", findings, checks)


def audit_provenance(document: Any, evidence_records: Sequence[Any] = (), provenance_records: Sequence[Any] = (), *, mode: Any = None) -> ValidationReport:
    return audit_truth(document, evidence_records, provenance_records, mode=mode)


def _privacy_findings(document: Any, mode: str) -> tuple[list[_Finding], dict[str, bool]]:
    findings: list[_Finding] = []
    text = _visible_text(document)
    if _SECRET.search(text):
        findings.append(_Finding("privacy", "credential", "Remove credential-like values from every visible section."))
    if _INTERNAL_URL.search(text):
        findings.append(_Finding("privacy", "internal_url", "Remove internal, local, file, or SSH URLs; retain verified public links only."))
    if _PRIVATE_LOG.search(text):
        findings.append(_Finding("privacy", "private_material", "Remove private logs, internal repository locations, and customer traces."))
    contact = _dict(_get(document, "contact", default={}))
    if mode == "public_portfolio" and contact.get("phone"):
        findings.append(_Finding("privacy", "public_phone", "Remove phone number from public portfolio mode."))
    if mode == "targeted_application":
        if not contact.get("email"):
            findings.append(_Finding("privacy", "application_email", "Add an appropriate application email address."))
        if not contact.get("name"):
            findings.append(_Finding("privacy", "application_name", "Add the candidate name for an application resume."))
    checks = {"no_credentials": not bool(_SECRET.search(text)), "no_internal_urls": not bool(_INTERNAL_URL.search(text)), "no_private_material": not bool(_PRIVATE_LOG.search(text)), "contact_appropriate": not any(f.code in {"public_phone", "application_email", "application_name"} for f in findings)}
    return findings, checks


def audit_privacy(document: Any, *, mode: Any = None) -> ValidationReport:
    findings, checks = _privacy_findings(document, _mode(mode, document))
    return _report("privacy", findings, checks)


def audit_resume(document: Any, evidence_records: Sequence[Any] = (), mappings: Sequence[Any] = (), requirements: Sequence[Any] = (), provenance_records: Sequence[Any] = (), *, mode: Any = None) -> ValidationReport:
    """Run all five audit dimensions and return one actionable report."""
    del mappings  # mappings influence composition; truth is checked against selected records.
    mode_value = _mode(mode, document)
    category_results = []
    for category, producer in (
        ("ats", lambda: _ats_findings(document, requirements)),
        ("hr", lambda: _hr_findings(document)),
        ("technical", lambda: _technical_findings(document, evidence_records)),
        ("truth", lambda: _truth_findings(document, evidence_records, provenance_records, mode_value)),
        ("privacy", lambda: _privacy_findings(document, mode_value)),
    ):
        findings, checks = producer()
        category_results.append((category, findings, checks))
    all_findings = [finding for _, findings, _ in category_results for finding in findings]
    errors = [finding.actionable for finding in all_findings if finding.error]
    warnings = [finding.actionable for finding in all_findings if not finding.error]
    checks = {category: not any(finding.error for finding in findings) for category, findings, _ in category_results}
    details = {category: {"checks": subchecks, "errors": sum(f.error for f in findings), "warnings": sum(not f.error for f in findings)} for category, findings, subchecks in category_results}
    return ValidationReport(success=not errors, checks=checks, errors=errors, warnings=warnings, details=details)


run_audits = audit_resume
