"""Deterministic evidence normalization, matching, and incremental refresh."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from china_targeted_resume.models import (
    CandidateExperienceDurationFact,
    EvidenceCandidate,
    EvidenceMapping,
    EvidenceRecord,
    ExperienceDurationDiagnosticBinding,
    FactState,
    Freshness,
    Requirement,
    RequirementOrigin,
    parse_candidate_experience_duration_fact,
    normalize_experience_scope,
    RoleMatchState,
)
from china_targeted_resume.policy import apply_evidence_policy


NEAR_MATCH_EXPERIENCE_SHORTFALL = 0.25
_APPROXIMATE = re.compile(r"(?:约|大约|近|超过|不少于|approximately|about|around|roughly|~|≈)", re.I)
_RANGE = re.compile(r"(?:\b\d+(?:\.\d+)?\s*[-–—~至到]\s*\d+(?:\.\d+)?\b|数十|数百|several|between)", re.I)
_STAGE = re.compile(r"(?:阶段|试点|原型|PoC|pilot|prototype|phase|截至|at the time)", re.I)
_DATE = re.compile(r"(?:\b(?:19|20)\d{2}(?:[-/.年]\d{1,2})?|Q[1-4]|季度|当时|期间|as of|during)\b", re.I)
_TEAM = re.compile(r"(?:团队|协作|参与|配合|共同|team|collaborat|contribut|participat|support)", re.I)
_METRIC = re.compile(r"(?:\d[\d,.]*\s*(?:%|倍|万|亿|ms|s|秒|分钟|小时|天|人|个|次|TPS|QPS|RPS|MB|GB)?)", re.I)
_CONTRIBUTION = re.compile(
    r"(?:主导|负责|参与|协作|支持|设计|实现|优化|维护|led|owned|responsible for|"
    r"contributed|participated|collaborated|supported|designed|implemented|optimized|maintained)",
    re.I,
)
_PERSONAL_FORBIDDEN_SOURCE_TYPES = {
    "company-research",
    "company_research",
    "growth-roadmap",
    "growth_roadmap",
    "roadmap",
}
KNOWN_SKILLS = (
    "Megatron-LM", "Distributed systems", "Incident response", "TypeScript",
    "JavaScript", "PostgreSQL", "Kubernetes", "TensorFlow", "DeepSpeed",
    "Prometheus", "Networking", "PyTorch", "Python", "Docker", "Linux",
    "Grafana", "MySQL", "Redis", "Kafka", "gRPC", "ROS 2", "CUDA", "FSDP",
    "DDP", "GPU", "HTTP", "API", "CI/CD", "C++", "C#", "Rust", "Java",
    "JAX", "Go", "Terraform", "Coder", "Docker Swarm", "Flask",
    "SQLAlchemy", "CMake", "vcpkg", "Electron", "Vue", "tree-sitter",
    "CTags", "WebSocket", "NETCONF", "Spring Boot", "Spring Cloud", "Gin",
    "Kratos", "OpenTelemetry", "OpenSearch", "Loki", "eBPF",
)
_STRICT_COMPOUND_SKILLS = tuple(
    skill
    for skill in KNOWN_SKILLS
    if skill
    not in {
        "Distributed systems",
        "Incident response",
        "Networking",
        "GPU",
        "HTTP",
        "API",
        "CI/CD",
        "Coder",
    }
)
_SKILL_PATTERNS = {
    skill: re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(skill)}(?![A-Za-z0-9])",
        re.I,
    )
    for skill in KNOWN_SKILLS
}
_TECH_STACK_SECTION = re.compile(r"(?:technology stack|tech stack|技术栈)", re.I)
_COVERAGE_INVENTORY = re.compile(
    r"(?:覆盖|支持|适配|面向)[^。；;\n]{0,160}(?:语言|languages?)|"
    r"\b(?:supports?|covers?|targets?)\b[^.;\n]{0,160}\blanguages?\b",
    re.I,
)
_DIRECT_SKILL_USE = (
    r"(?:使用|采用|基于|以|用|using|built with|implemented (?:in|with)|written in)"
    r"[^。；;\n]{{0,48}}{skill}|"
    r"{skill}[^。；;\n]{{0,36}}"
    r"(?:开发|实现|编写|服务|组件|模块|脚本|接口|API|development|service|module|script)"
)


def _skill_pattern(skill: str) -> re.Pattern[str]:
    return _SKILL_PATTERNS.get(skill) or re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(skill)}(?![A-Za-z0-9])",
        re.I,
    )


def text_mentions_skill(text: str, skill: str) -> bool:
    return _skill_pattern(skill).search(text) is not None


def technology_terms(text: str) -> tuple[str, ...]:
    return tuple(
        skill for skill in _STRICT_COMPOUND_SKILLS if text_mentions_skill(text, skill)
    )


def claim_supports_skill(claim: str, skill: str, *, section: str = "") -> bool:
    """Reject inventory/coverage mentions that do not demonstrate using a skill."""
    pattern = _skill_pattern(skill)
    if pattern.search(claim) is None:
        return False
    if re.search(
        _DIRECT_SKILL_USE.format(skill=f"(?:{pattern.pattern})"),
        claim,
        re.I,
    ):
        return True
    if _COVERAGE_INVENTORY.search(claim):
        return False
    if _TECH_STACK_SECTION.search(section):
        return False
    return True


def _is_nonpersonal_source(source: Any) -> bool:
    source_type = str(_get(source, "source_type", "") or "").casefold()
    path = str(_get(source, "path", "") or "").casefold()
    normalized = re.sub(r"[\s_]+", "-", f"{source_type} {path}")
    return (
        source_type in _PERSONAL_FORBIDDEN_SOURCE_TYPES
        or ("company" in normalized and "research" in normalized)
        or ("growth" in normalized and "roadmap" in normalized)
    )

_STATE_ORDER = {
    RoleMatchState.DIRECT_EVIDENCE: 0,
    RoleMatchState.TRANSFERABLE_EXPERIENCE: 1,
    RoleMatchState.KNOWLEDGE_WITHOUT_PRACTICE: 2,
    RoleMatchState.CLEAR_GAP: 3,
    RoleMatchState.PENDING_CONFIRMATION: 4,
}


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _dump(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return dict(value)
    return vars(value).copy() if hasattr(value, "__dict__") else {}


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)

def assess_experience_duration_near_match(
    mapping: EvidenceMapping | Mapping[str, Any],
    requirement: Requirement | Mapping[str, Any],
    records: Sequence[EvidenceRecord | Mapping[str, Any]] = (),
    *,
    maximum_shortfall: float = NEAR_MATCH_EXPERIENCE_SHORTFALL,
) -> tuple[float, float, float] | None:
    """Diagnose one explicit duration only from owning candidate facts."""

    if not 0 <= maximum_shortfall < 1:
        raise ValueError("maximum_shortfall must be in [0, 1)")
    canonical_mapping = (
        mapping
        if isinstance(mapping, EvidenceMapping)
        else EvidenceMapping.model_validate(mapping)
    )
    canonical_requirement = (
        requirement
        if isinstance(requirement, Requirement)
        else Requirement.model_validate(requirement)
    )
    diagnostic = canonical_mapping.experience_duration_diagnostic
    threshold = canonical_requirement.experience_duration
    if (
        diagnostic is None
        or threshold is None
        or canonical_requirement.origin is not RequirementOrigin.EXPLICIT
        or canonical_requirement.requirement_id
        != canonical_mapping.requirement_id
        or normalize_experience_scope(diagnostic.required_scope)
        != normalize_experience_scope(threshold.scope)
        or diagnostic.unit != threshold.unit
        or diagnostic.required_min_years
        != threshold.required_min_years
        or diagnostic.required_max_years
        != threshold.required_max_years
    ):
        return None
    records_by_id = {
        record.evidence_id: record
        for raw in records
        for record in [
            raw
            if isinstance(raw, EvidenceRecord)
            else EvidenceRecord.model_validate(raw)
        ]
    }
    for evidence_id in diagnostic.evidence_refs:
        record = records_by_id.get(evidence_id)
        if record is None or record.experience_duration_fact is None:
            return None
        fact = record.experience_duration_fact
        if (
            normalize_experience_scope(fact.scope)
            != normalize_experience_scope(diagnostic.candidate_scope)
            or fact.unit != diagnostic.unit
            or fact.years != diagnostic.candidate_years
            or fact.checked_at != diagnostic.checked_at
        ):
            return None
    shortfall = (
        threshold.required_min_years - diagnostic.candidate_years
    ) / threshold.required_min_years
    if shortfall > maximum_shortfall:
        return None
    return (
        diagnostic.candidate_years,
        threshold.required_min_years,
        shortfall,
    )


def bind_experience_duration_diagnostics(
    mappings: Sequence[EvidenceMapping | Mapping[str, Any]],
    requirements: Sequence[Requirement | Mapping[str, Any]],
    records: Sequence[EvidenceRecord | Mapping[str, Any]],
    bindings: Sequence[
        ExperienceDurationDiagnosticBinding | Mapping[str, Any]
    ],
) -> list[EvidenceMapping]:
    """Bind duration diagnostics only after revalidating owning evidence facts."""

    canonical_mappings = [
        mapping
        if isinstance(mapping, EvidenceMapping)
        else EvidenceMapping.model_validate(mapping)
        for mapping in mappings
    ]
    if not bindings:
        return canonical_mappings
    canonical_requirements = {
        requirement.requirement_id: requirement
        for raw in requirements
        for requirement in [
            raw
            if isinstance(raw, Requirement)
            else Requirement.model_validate(raw)
        ]
    }
    canonical_records = {
        record.evidence_id: record
        for raw in records
        for record in [
            raw
            if isinstance(raw, EvidenceRecord)
            else EvidenceRecord.model_validate(raw)
        ]
    }
    canonical_bindings = [
        binding
        if isinstance(binding, ExperienceDurationDiagnosticBinding)
        else ExperienceDurationDiagnosticBinding.model_validate(binding)
        for binding in bindings
    ]
    binding_ids = [binding.requirement_id for binding in canonical_bindings]
    if len(binding_ids) != len(set(binding_ids)):
        raise ValueError(
            "experience duration diagnostics must bind each requirement at most once"
        )
    mapping_by_id = {
        mapping.requirement_id: mapping
        for mapping in canonical_mappings
    }
    for binding in canonical_bindings:
        requirement = canonical_requirements.get(binding.requirement_id)
        if requirement is None:
            raise ValueError(
                f"experience duration diagnostic references unknown requirement: {binding.requirement_id}"
            )
        if requirement.origin is not RequirementOrigin.EXPLICIT:
            raise ValueError(
                "experience duration diagnostics require explicit requirements"
            )
        threshold = requirement.experience_duration
        if threshold is None:
            raise ValueError(
                "experience duration diagnostic requires a verbatim-backed requirement threshold"
            )
        diagnostic = binding.diagnostic
        if (
            normalize_experience_scope(diagnostic.required_scope)
            != normalize_experience_scope(threshold.scope)
            or diagnostic.unit != threshold.unit
            or diagnostic.required_min_years
            != threshold.required_min_years
            or diagnostic.required_max_years
            != threshold.required_max_years
        ):
            raise ValueError(
                "experience duration diagnostic required scope and threshold must match the verbatim requirement"
            )
        mapping = mapping_by_id.get(binding.requirement_id)
        if mapping is None:
            raise ValueError(
                f"experience duration diagnostic has no evidence mapping: {binding.requirement_id}"
            )
        for evidence_id in diagnostic.evidence_refs:
            record = canonical_records.get(evidence_id)
            if record is None:
                raise ValueError(
                    f"experience duration diagnostic references unknown evidence record: {evidence_id}"
                )
            fact = record.experience_duration_fact
            if fact is None:
                raise ValueError(
                    f"experience duration diagnostic evidence has no owning duration fact: {evidence_id}"
                )
            if (
                normalize_experience_scope(fact.scope)
                != normalize_experience_scope(diagnostic.candidate_scope)
                or fact.unit != diagnostic.unit
                or fact.years != diagnostic.candidate_years
                or fact.checked_at != diagnostic.checked_at
            ):
                raise ValueError(
                    f"experience duration diagnostic candidate value does not match owning evidence: {evidence_id}"
                )
        payload = mapping.model_dump(mode="python")
        payload["experience_duration_diagnostic"] = diagnostic
        mapping_by_id[binding.requirement_id] = (
            EvidenceMapping.model_validate(payload)
        )
    return [
        mapping_by_id[mapping.requirement_id]
        for mapping in canonical_mappings
    ]


def _state(value: Any) -> RoleMatchState:
    if isinstance(value, RoleMatchState):
        return value
    return RoleMatchState(_value(value))




def _direct_technology_coverage(
    requirement: Any,
    records: Sequence[EvidenceRecord],
) -> tuple[bool, tuple[str, ...]]:
    requirement_text = str(_get(requirement, "text", ""))
    required = technology_terms(requirement_text)
    if len(required) < 2:
        return True, ()
    supported = {
        skill
        for skill in required
        if any(
            claim_supports_skill(
                record.safe_claim,
                skill,
                section=str(record.source.section or ""),
            )
            for record in records
        )
    }
    alternatives = (
        len(required) == 2
        and re.search(r"\b(?:or)\b|或|\s/\s", requirement_text, re.I) is not None
    )
    minimum = 1 if alternatives else len(required)
    missing = tuple(skill for skill in required if skill not in supported)
    return len(supported) >= minimum, missing


def detect_metric_qualifiers(text: str) -> dict[str, Any]:
    """Describe precision qualifiers that must survive claim composition."""

    text = text if isinstance(text, str) else ""
    kinds = [
        name
        for name, pattern in (
            ("approximate", _APPROXIMATE),
            ("range", _RANGE),
            ("stage", _STAGE),
            ("date", _DATE),
            ("team", _TEAM),
        )
        if pattern.search(text)
    ]
    return {
        "has_metric": _METRIC.search(text) is not None,
        "qualifiers": kinds,
        "approximate": "approximate" in kinds,
        "range": "range" in kinds,
        "stage": "stage" in kinds,
        "date": "date" in kinds,
        "team": "team" in kinds,
    }


def _metric_precision(text: str) -> str | None:
    detected = detect_metric_qualifiers(text)
    if not detected["has_metric"]:
        return None
    qualifiers = detected["qualifiers"]
    return ",".join(qualifiers) if qualifiers else "exact-as-sourced"


def _forbidden_expansions(text: str) -> list[str]:
    restrictions = ["Do not strengthen the contribution verb or responsibility scope."]
    qualifiers = detect_metric_qualifiers(text)["qualifiers"]
    if qualifiers:
        restrictions.append("Do not remove sourced metric qualifiers: " + ", ".join(qualifiers) + ".")
    if _METRIC.search(text):
        restrictions.append("Do not increase, normalize, or extrapolate the sourced metric.")
    return restrictions


def _contribution_scope(text: str) -> str:
    match = _CONTRIBUTION.search(text)
    return match.group(0) if match else "scope not stated; do not infer ownership"


def build_evidence_record(
    candidate: EvidenceCandidate | Mapping[str, Any],
    requirement_ids: Sequence[str],
    *,
    mode: Any,
    now: datetime | date | None = None,
) -> EvidenceRecord | None:
    """Promote a policy-eligible candidate without strengthening its claim."""

    try:
        item = candidate if isinstance(candidate, EvidenceCandidate) else EvidenceCandidate.model_validate(candidate)
    except (TypeError, ValueError):
        return None
    if _is_nonpersonal_source(item.source):
        return None
    if not item.source.path or not item.source.section or not item.source.source_hash:
        return None
    decision = apply_evidence_policy(item, mode, now=now)
    if not decision.allowed_as_candidate:
        return None
    claim = item.proposed_claim
    if not claim.strip():
        return None
    duration_data = parse_candidate_experience_duration_fact(claim)
    duration_fact = (
        CandidateExperienceDurationFact.model_validate(duration_data)
        if duration_data is not None and item.source_span is not None
        else None
    )
    checked_at = (
        duration_fact.checked_at
        if duration_fact is not None
        else item.source.accessed_at
    )
    freshness = Freshness(
        dynamic=(
            item.fact_state == FactState.F3
            or duration_fact is not None
        ),
        checked_at=checked_at,
        stale=(
            item.fact_state == FactState.F3
            and checked_at is None
        ),
    )
    evidence_id = "ev-" + hashlib.sha256(
        f"{item.candidate_id}\0{item.source.path}\0{item.source.section}\0{item.source.source_hash}".encode()
    ).hexdigest()[:20]
    match_state = item.match_state
    if item.fact_state in {FactState.F4, FactState.F5}:
        match_state = RoleMatchState.PENDING_CONFIRMATION
    return EvidenceRecord(
        evidence_id=evidence_id,
        requirement_ids=list(dict.fromkeys(requirement_ids)),
        source=item.source,
        source_span=item.source_span,
        fact_state=item.fact_state,
        disclosure=item.disclosure,
        match_state=match_state,
        contribution_scope=_contribution_scope(claim),
        metric_precision=_metric_precision(claim),
        safe_claim=claim,
        forbidden_expansions=_forbidden_expansions(claim),
        freshness=freshness,
        experience_duration_fact=duration_fact,
    )


def _mapping_for(requirement: Any, records: Sequence[EvidenceRecord]) -> EvidenceMapping:
    requirement_id = str(_get(requirement, "requirement_id", ""))
    linked = [record for record in records if requirement_id in record.requirement_ids]
    if not linked:
        return EvidenceMapping(
            requirement_id=requirement_id,
            match_state=RoleMatchState.PENDING_CONFIRMATION,
            selection_reason="No eligible evidence is linked to this requirement.",
            missing_evidence=["Confirm current personal evidence from an owning source section."],
        )
    best = min((_state(record.match_state) for record in linked), key=lambda state: _STATE_ORDER[state])
    selected = [record for record in linked if _state(record.match_state) == best]
    risks: list[str] = []
    missing_evidence: list[str] = []
    selection_reason = f"Selected the strongest eligible linked state: {best.value}."
    if best == RoleMatchState.DIRECT_EVIDENCE:
        covered, missing_skills = _direct_technology_coverage(requirement, selected)
        if not covered:
            best = RoleMatchState.TRANSFERABLE_EXPERIENCE
            selected = [
                record
                for record in linked
                if _state(record.match_state)
                in {
                    RoleMatchState.DIRECT_EVIDENCE,
                    RoleMatchState.TRANSFERABLE_EXPERIENCE,
                }
            ]
            selection_reason = (
                "Downgraded to 可迁移经验 because direct evidence does not cover "
                "enough named technologies in the compound requirement."
            )
            missing_evidence.append(
                "Add direct evidence for more named technologies; missing: "
                + ", ".join(missing_skills)
                + "."
            )
        else:
            risks.append("Validate contribution scope and all metric qualifiers in interview.")
    if any(record.freshness.dynamic for record in selected):
        risks.append("Dynamic evidence requires current verification.")
    usable_ids = [record.evidence_id for record in selected if not record.freshness.stale]
    duration_threshold = _get(requirement, "experience_duration")
    if duration_threshold is not None:
        duration_scope = str(
            _get(duration_threshold, "scope", "")
        )
        duration_records = [
            record
            for record in linked
            if record.experience_duration_fact is not None
            and normalize_experience_scope(
                record.experience_duration_fact.scope
            )
            == normalize_experience_scope(duration_scope)
            and _state(record.match_state)
            in {
                RoleMatchState.DIRECT_EVIDENCE,
                RoleMatchState.TRANSFERABLE_EXPERIENCE,
            }
            and not record.freshness.stale
        ]
        if duration_records:
            usable_ids = list(
                dict.fromkeys(
                    [
                        *usable_ids,
                        *(
                            record.evidence_id
                            for record in duration_records
                        ),
                    ]
                )
            )
            risks.append(
                "Validate the checked atomic experience-duration fact against the explicit threshold."
            )
        else:
            missing_evidence.append(
                "Add one checked atomic duration fact for the explicit experience threshold."
            )
    if not usable_ids:
        best = RoleMatchState.PENDING_CONFIRMATION
        missing_evidence = ["Current eligible evidence is required."]
    return EvidenceMapping(
        requirement_id=requirement_id,
        match_state=best,
        evidence_ids=usable_ids,
        selection_reason=selection_reason,
        resume_priority=float(_get(requirement, "confidence", 0.0) or 0.0),
        interview_risks=risks,
        missing_evidence=missing_evidence,
    )


def build_evidence_map(
    requirements: Sequence[Any],
    candidates: Sequence[EvidenceCandidate | Mapping[str, Any]],
    *,
    mode: Any,
    now: datetime | date | None = None,
) -> list[EvidenceMapping]:
    """Build one canonical five-state mapping for every requirement."""

    requirement_ids = {str(_get(req, "requirement_id", "")) for req in requirements}
    records: list[EvidenceRecord] = []
    for candidate in candidates:
        linked = [rid for rid in _get(candidate, "requirement_ids", ()) if rid in requirement_ids]
        record = build_evidence_record(candidate, linked, mode=mode, now=now)
        if record is not None:
            records.append(record)
    return [_mapping_for(requirement, records) for requirement in requirements]


class RefreshMatchResult(BaseModel):
    """Explicit incremental-refresh boundary and result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mappings: list[EvidenceMapping]
    refreshed_requirement_ids: list[str]
    unchanged_requirement_ids: list[str]


def refresh_match(
    previous_mappings: Sequence[EvidenceMapping | Mapping[str, Any]],
    requirements: Sequence[Any],
    evidence_records: Sequence[EvidenceRecord | Mapping[str, Any]],
    changed_source_hashes: Sequence[str] | Mapping[str, str | Sequence[str]],
) -> RefreshMatchResult:
    """Re-evaluate only requirements linked to changed personal owning sections."""

    if isinstance(changed_source_hashes, Mapping):
        changed = set(changed_source_hashes)
        for values in changed_source_hashes.values():
            changed.update([values] if isinstance(values, str) else values)
    else:
        changed = set(changed_source_hashes)
    records = [r if isinstance(r, EvidenceRecord) else EvidenceRecord.model_validate(r) for r in evidence_records]
    affected: set[str] = set()
    for record in records:
        if _is_nonpersonal_source(record.source):
            continue
        if record.source.path and record.source.section and record.source.source_hash in changed:
            affected.update(record.requirement_ids)
    previous = {
        str(_get(mapping, "requirement_id")): (
            mapping if isinstance(mapping, EvidenceMapping) else EvidenceMapping.model_validate(mapping)
        )
        for mapping in previous_mappings
    }
    requirement_by_id = {str(_get(req, "requirement_id", "")): req for req in requirements}
    result: list[EvidenceMapping] = []
    refreshed: list[str] = []
    unchanged: list[str] = []
    for requirement_id, requirement in requirement_by_id.items():
        if requirement_id in affected:
            result.append(_mapping_for(requirement, records))
            refreshed.append(requirement_id)
        elif requirement_id in previous:
            result.append(previous[requirement_id])
            unchanged.append(requirement_id)
        else:
            result.append(_mapping_for(requirement, records))
            refreshed.append(requirement_id)
    return RefreshMatchResult(
        mappings=result,
        refreshed_requirement_ids=refreshed,
        unchanged_requirement_ids=unchanged,
    )
