"""Orthogonal gap classification for role requirements."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from china_targeted_resume.models import EvidenceMapping, Gap, GapSeverity, RoleMatchState


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _severity(requirement: Any) -> GapSeverity:
    """Derive impact from requirement criticality, never from match state."""

    if bool(_get(requirement, "hard_gate", False)) or str(_value(_get(requirement, "priority", ""))).lower() == "critical":
        return GapSeverity.CRITICAL
    necessity = str(_value(_get(requirement, "necessity", ""))).lower()
    priority = str(_value(_get(requirement, "priority", "medium"))).lower()
    if necessity == "required" or priority == "high":
        return GapSeverity.MAJOR
    return GapSeverity.MINOR


def build_gaps(requirements: Sequence[Any], mappings: Sequence[Any]) -> list[Gap]:
    """Build confirmed gaps and pending questions; omit direct-evidence pseudo-gaps."""

    requirement_by_id = {str(_get(item, "requirement_id", "")): item for item in requirements}
    result: list[Gap] = []
    for raw_mapping in mappings:
        mapping = raw_mapping if isinstance(raw_mapping, EvidenceMapping) else EvidenceMapping.model_validate(raw_mapping)
        requirement = requirement_by_id.get(mapping.requirement_id)
        if requirement is None or mapping.match_state == RoleMatchState.DIRECT_EVIDENCE:
            continue
        pending = mapping.match_state == RoleMatchState.PENDING_CONFIRMATION
        severity = None if pending else _severity(requirement)
        requirement_text = str(_get(requirement, "text", mapping.requirement_id))
        if pending:
            reason = "Evidence status is unresolved; severity is intentionally unset until confirmation."
            impact = "Application readiness remains unknown for this requirement."
            directions = list(mapping.missing_evidence) or ["Confirm whether current personal evidence exists."]
        else:
            necessity = str(_value(_get(requirement, "necessity", "unknown")))
            reason = (
                f"Requirement ({necessity}) is mapped as {mapping.match_state.value}; "
                "impact is assessed independently."
            )
            impact = f"{severity.value} impact for requirement: {requirement_text}"
            directions = list(mapping.missing_evidence) or ["Acquire or validate evidence matching the required depth."]
        gap_id = "gap-" + hashlib.sha256(mapping.requirement_id.encode()).hexdigest()[:20]
        result.append(
            Gap(
                gap_id=gap_id,
                requirement_id=mapping.requirement_id,
                match_state=mapping.match_state,
                severity=severity,
                job_impact=impact,
                reason=reason,
                baseline_evidence_refs=list(mapping.evidence_ids),
                validation_direction=directions,
            )
        )
    return result
