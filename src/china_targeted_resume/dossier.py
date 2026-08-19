"""Seven-file role dossier serialization and source-hash refresh."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .models import RoleDossierIR

DOSSIER_FILES = (
    "job-description.md",
    "requirement-analysis.md",
    "competency-model.md",
    "evidence-mapping.md",
    "gap-analysis.md",
    "interview-preparation.md",
    "sources.md",
)
_POSITIVE_STATES = {"已有直接证据", "可迁移经验", "有知识无实践"}


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=False)
    return dict(value)


def _md(value: Any) -> str:
    return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ")


def _source_key(source: Mapping[str, Any]) -> str:
    return str(source.get("path") or source.get("url") or source.get("title") or "unknown-source")


def source_hashes(dossier: RoleDossierIR | Mapping[str, Any]) -> dict[str, str]:
    data = _dump(dossier)
    result: dict[str, str] = {}
    for raw in data.get("sources") or []:
        source = _dump(raw)
        key = _source_key(source)
        digest = source.get("source_hash")
        if digest:
            result[key] = str(digest)
    return result


def _target_block(data: Mapping[str, Any]) -> list[str]:
    target = _dump(data["target_context"])
    return [
        f"- Target basis: `{_md(target.get('target_basis'))}`",
        f"- Company: {_md(target.get('company'))}",
        f"- Role: {_md(target.get('role'))}",
        f"- JD completeness: `{_md(target.get('jd_completeness'))}`",
        f"- JD source date: {_md(target.get('jd_source_date'))}",
        f"- Staleness risk: `{_md(target.get('staleness_risk'))}`",
        *[f"- Limitation: {_md(item)}" for item in target.get("limitations") or []],
    ]


def _requirements_section(data: Mapping[str, Any]) -> str:
    lines = ["<!-- generated:requirements:start -->", "## Requirements", "", "| ID | Category | Necessity | Hard gate | Summary | Source |", "|---|---|---|---:|---|---|"]
    for raw in data.get("requirements") or []:
        req = _dump(raw)
        lines.append(
            f"| `{_md(req.get('requirement_id'))}` | {_md(req.get('category'))} | "
            f"{_md(req.get('necessity'))} | {'yes' if req.get('hard_gate') else 'no'} | "
            f"{_md(req.get('text'))} | `{_md(req.get('source_ref'))}` |"
        )
        if str(req.get("origin")) == "inferred":
            lines.append(
                f"| ↳ inference | | confidence={_md(req.get('confidence'))} | no | "
                f"basis: {_md(req.get('inference_basis'))} | `{_md(req.get('source_ref'))}` |"
            )
    lines.extend(["", "## Application constraints", "", "| ID | Kind | Required value | Candidate status | Impact |", "|---|---|---|---|---|"])
    for raw in data.get("application_constraints") or []:
        item = _dump(raw)
        lines.append(
            f"| `{_md(item.get('constraint_id'))}` | {_md(item.get('kind'))} | "
            f"{_md(item.get('required_value'))} | `{_md(item.get('status', 'unknown'))}` | "
            f"{_md(item.get('impact'))} |"
        )
    lines.extend(["", "<!-- generated:requirements:end -->"])
    return "\n".join(lines)


def _anomalies_section(data: Mapping[str, Any]) -> str:
    lines = ["<!-- generated:anomalies:start -->", "## Anomalies and conflicts", ""]
    target = _dump(data.get("target_context") or {})
    anomalies = list(data.get("anomalies") or []) + [
        f"SOURCE_CONFLICT {item}" for item in target.get("conflicts") or []
    ]
    lines.extend(f"- {_md(item)}" for item in anomalies)
    if not anomalies:
        lines.append("- None detected.")
    lines.append("<!-- generated:anomalies:end -->")
    return "\n".join(lines)


def _competencies_section(data: Mapping[str, Any]) -> str:
    lines = ["<!-- generated:competencies:start -->", "## Job expectations", "", "| ID | Dimension | Expected depth | Scale / scope | Requirement IDs | Source refs |", "|---|---|---|---|---|---|"]
    for raw in data.get("competencies") or []:
        item = _dump(raw)
        scope = item.get("system_scale") or item.get("responsibility_scope") or "not specified"
        lines.append(
            f"| `{_md(item.get('competency_id'))}` | {_md(item.get('dimension'))} | "
            f"{_md(item.get('expected_depth'))} | {_md(scope)} | "
            f"{', '.join(f'`{_md(value)}`' for value in item.get('requirement_ids') or [])} | "
            f"{', '.join(f'`{_md(value)}`' for value in item.get('source_refs') or [])} |"
        )
    lines.extend(["", "<!-- generated:competencies:end -->"])
    return "\n".join(lines)


def _relative_personal_ref(path: str) -> str:
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"personal evidence reference must be a safe relative path: {path!r}")
    return pure.as_posix()


def _evidence_markdown(data: Mapping[str, Any]) -> str:
    records = {_dump(item).get("evidence_id"): _dump(item) for item in data.get("evidence_records") or []}
    lines = ["# Evidence mapping", "", "| Requirement | State | Evidence references | Selection reason |", "|---|---|---|---|"]
    for raw in data.get("evidence_mappings") or []:
        item = _dump(raw)
        state = str(item.get("match_state"))
        refs: list[str] = []
        for evidence_id in item.get("evidence_ids") or []:
            record = records.get(evidence_id)
            if record is None:
                raise ValueError(f"evidence mapping references unknown evidence ID: {evidence_id}")
            source = _dump(record.get("source") or {})
            path = source.get("path")
            if state in _POSITIVE_STATES and not path:
                raise ValueError(f"positive evidence {evidence_id} needs a personal-data relative path")
            refs.append(f"[{_md(evidence_id)}]({_relative_personal_ref(path)})" if path else f"`{_md(evidence_id)}`")
        if state in _POSITIVE_STATES and not refs:
            raise ValueError(f"positive mapping {item.get('requirement_id')} needs evidence references")
        lines.append(
            f"| `{_md(item.get('requirement_id'))}` | `{_md(state)}` | "
            f"{', '.join(refs) or 'none'} | {_md(item.get('selection_reason'))} |"
        )
    return "\n".join(lines)


def _gaps_markdown(data: Mapping[str, Any]) -> str:
    lines = ["# Gap analysis", "", "| Gap | Requirement | Match state | Severity | Job impact | Verification | Roadmap |", "|---|---|---|---|---|---|---|"]
    for raw in data.get("gaps") or []:
        item = _dump(raw)
        lines.append(
            f"| `{_md(item.get('gap_id'))}` | `{_md(item.get('requirement_id'))}` | "
            f"`{_md(item.get('match_state'))}` | {_md(item.get('severity'))} | "
            f"{_md(item.get('job_impact'))} | {_md('; '.join(item.get('validation_direction') or []))} | "
            f"{_md('; '.join(item.get('roadmap_refs') or []))} |"
        )
    return "\n".join(lines)


def _interview_markdown(data: Mapping[str, Any]) -> str:
    lines = ["# Interview preparation", ""]
    questions = data.get("interview_questions") or []
    lines.extend(f"- {_md(item)}" for item in questions)
    if not questions:
        lines.append("- No role-specific questions generated.")
    return "\n".join(lines)


def _sources_markdown(data: Mapping[str, Any]) -> str:
    lines = ["# Sources", "", "| Reference | Type | Publisher | Published | Accessed | Hash |", "|---|---|---|---|---|---|"]
    for raw in data.get("sources") or []:
        item = _dump(raw)
        lines.append(
            f"| `{_md(_source_key(item))}` | {_md(item.get('source_type'))} | "
            f"{_md(item.get('publisher'))} | {_md(item.get('published_at'))} | "
            f"{_md(item.get('accessed_at'))} | `{_md(item.get('source_hash'))}` |"
        )
    lines.extend(["", _anomalies_section(data)])
    return "\n".join(lines)


def render_dossier_files(
    dossier: RoleDossierIR | Mapping[str, Any], *, job_description: str
) -> dict[str, str]:
    """Render exactly seven owning Markdown files in memory."""
    data = _dump(dossier)
    job_lines = ["# Job description", "", *_target_block(data), "", "## Complete source text", "", job_description]
    requirement_text = "# Requirement analysis\n\n" + _requirements_section(data) + "\n\n" + _anomalies_section(data)
    return {
        "job-description.md": "\n".join(job_lines).rstrip() + "\n",
        "requirement-analysis.md": requirement_text.rstrip() + "\n",
        "competency-model.md": ("# Competency model\n\n" + _competencies_section(data)).rstrip() + "\n",
        "evidence-mapping.md": _evidence_markdown(data).rstrip() + "\n",
        "gap-analysis.md": _gaps_markdown(data).rstrip() + "\n",
        "interview-preparation.md": _interview_markdown(data).rstrip() + "\n",
        "sources.md": _sources_markdown(data).rstrip() + "\n",
    }


def build_role_dossier(
    *,
    target_context: Any,
    requirements: Any = (),
    competencies: Any = (),
    application_constraints: Any = (),
    evidence_candidates: Any = (),
    evidence_records: Any = (),
    evidence_mappings: Any = (),
    gaps: Any = (),
    application_recommendation: Any = None,
    roadmap_handoff: Any = (),
    provenance: Any = (),
    anomalies: Any = (),
    interview_questions: Any = (),
    sources: Any = (),
    source_manifest: Any = None,
    limitations: Any = (),
) -> RoleDossierIR:
    """Assemble and validate the run-local canonical dossier IR."""
    return RoleDossierIR.model_validate({
        "target_context": target_context,
        "requirements": list(requirements),
        "competencies": list(competencies),
        "application_constraints": list(application_constraints),
        "evidence_candidates": list(evidence_candidates),
        "evidence_records": list(evidence_records),
        "evidence_mappings": list(evidence_mappings),
        "gaps": list(gaps),
        "application_recommendation": application_recommendation,
        "roadmap_handoff": list(roadmap_handoff),
        "provenance": list(provenance),
        "anomalies": list(anomalies),
        "interview_questions": list(interview_questions),
        "sources": list(sources),
        "source_manifest": source_manifest,
        "limitations": list(limitations),
    })


def _secure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or path.is_symlink():
        raise ValueError("dossier output must be a real directory, not a symlink")
    os.chmod(resolved, 0o700)
    return resolved


def _secure_write(path: Path, content: str) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError(f"refusing to write through symlink: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def write_dossier(
    dossier: RoleDossierIR | Mapping[str, Any],
    output_dir: str | Path,
    *,
    job_description: str,
) -> tuple[Path, ...]:
    """Write the seven dossier owners with directory 0700 and files 0600."""
    directory = _secure_directory(Path(output_dir))
    rendered = render_dossier_files(dossier, job_description=job_description)
    if tuple(rendered) != DOSSIER_FILES:
        raise RuntimeError("dossier renderer violated the seven-file contract")
    written: list[Path] = []
    for name in DOSSIER_FILES:
        target = directory / name
        _secure_write(target, rendered[name])
        written.append(target)
    return tuple(written)


def _replace_owned_section(text: str, section: str, replacement: str) -> str:
    pattern = re.compile(
        rf"<!-- generated:{re.escape(section)}:start -->.*?"
        rf"<!-- generated:{re.escape(section)}:end -->",
        re.S,
    )
    if not pattern.search(text):
        raise ValueError(f"existing dossier lacks owned {section!r} section")
    return pattern.sub(lambda _: replacement, text, count=1)


def refresh_role(
    old_dossier: RoleDossierIR | Mapping[str, Any],
    new_dossier: RoleDossierIR | Mapping[str, Any],
    *,
    output_dir: str | Path | None = None,
) -> dict[str, str]:
    """Refresh only source-affected requirement/competency/anomaly sections.

    Unchanged hashes produce no output. Existing content outside generated
    markers—including human conclusions—is preserved byte-for-byte.
    """
    old_hashes = source_hashes(old_dossier)
    new_hashes = source_hashes(new_dossier)
    changed_sources = {
        key for key in old_hashes.keys() | new_hashes.keys()
        if old_hashes.get(key) != new_hashes.get(key)
    }
    if not changed_sources:
        return {}
    old_data, new_data = _dump(old_dossier), _dump(new_dossier)

    def touches(record: Mapping[str, Any], source_fields: tuple[str, ...]) -> bool:
        refs: set[str] = set()
        for field in source_fields:
            value = record.get(field)
            refs.update(value if isinstance(value, list) else [value] if value else [])
        return bool(refs & changed_sources)

    changed: dict[str, str] = {}
    if any(touches(_dump(item), ("source_ref",)) for item in new_data.get("requirements") or []) or old_data.get("requirements") != new_data.get("requirements"):
        changed["requirements"] = _requirements_section(new_data)
    if any(touches(_dump(item), ("source_refs",)) for item in new_data.get("competencies") or []) or old_data.get("competencies") != new_data.get("competencies"):
        changed["competencies"] = _competencies_section(new_data)
    old_conflicts = _dump(old_data.get("target_context") or {}).get("conflicts") or []
    new_conflicts = _dump(new_data.get("target_context") or {}).get("conflicts") or []
    if old_data.get("anomalies") != new_data.get("anomalies") or old_conflicts != new_conflicts:
        changed["anomalies"] = _anomalies_section(new_data)

    if output_dir is not None and changed:
        directory = _secure_directory(Path(output_dir))
        owners = {
            "requirements": ("requirement-analysis.md",),
            "competencies": ("competency-model.md",),
            "anomalies": ("requirement-analysis.md", "sources.md"),
        }
        by_file: dict[str, list[str]] = {}
        for section in changed:
            for owner in owners[section]:
                by_file.setdefault(owner, []).append(section)
        for filename, sections in by_file.items():
            path = directory / filename
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"refresh owner is missing or unsafe: {path}")
            text = path.read_text(encoding="utf-8")
            for section in sections:
                text = _replace_owned_section(text, section, changed[section])
            _secure_write(path, text)
    return changed


serialize_role_dossier = write_dossier
refresh_role_dossier = refresh_role
