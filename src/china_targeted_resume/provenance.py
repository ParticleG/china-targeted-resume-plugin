"""Claim provenance and confirmation-question generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel

from china_targeted_resume.models import (
    ConstraintStatus,
    DisclosureLevel,
    EvidenceRecord,
    FactState,
    OutputMode,
    ProvenanceRecord,
)
from china_targeted_resume.policy import apply_evidence_policy, detect_sensitive_content


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _source_ref(record: Any) -> str | None:
    source = _get(record, "source")
    if source is None:
        return None
    path = _get(source, "path")
    section = _get(source, "section")
    source_hash = _get(source, "source_hash")
    if not path or not section or not source_hash:
        return None
    hash_suffix = str(source_hash)
    if not hash_suffix.startswith("sha256:"):
        hash_suffix = f"sha256:{hash_suffix}"
    return f"{path}#{section}@{hash_suffix}"


def build_provenance(
    records: Sequence[Any],
    visible_claim_ids: Sequence[str],
    *,
    mode: OutputMode | str = OutputMode.TARGETED_APPLICATION,
) -> list[ProvenanceRecord]:
    """Build provenance only for visible, policy-eligible claims with owning hashes."""

    visible = set(visible_claim_ids)
    default_mode = mode if isinstance(mode, OutputMode) else OutputMode(mode)
    result: list[ProvenanceRecord] = []
    for raw in records:
        if isinstance(raw, ProvenanceRecord):
            decision = apply_evidence_policy(raw, raw.output_mode)
            if (
                raw.claim_id in visible
                and decision.allowed_in_output
                and not detect_sensitive_content(raw.rendered_claim)
            ):
                result.append(raw)
            continue
        claim_id = str(_get(raw, "claim_id", _get(raw, "evidence_id", "")))
        if not claim_id or claim_id not in visible:
            continue
        raw_mode = _get(raw, "output_mode")
        try:
            output_mode = OutputMode(_value(raw_mode)) if raw_mode is not None else default_mode
        except (TypeError, ValueError):
            continue
        decision = apply_evidence_policy(raw, output_mode)
        if not decision.allowed_in_output:
            continue
        source_ref = _source_ref(raw)
        if source_ref is None:
            continue
        evidence_id = str(_get(raw, "evidence_id", ""))
        rendered_claim = str(_get(raw, "rendered_claim", _get(raw, "safe_claim", "")))
        if not evidence_id or not rendered_claim or detect_sensitive_content(rendered_claim):
            continue
        try:
            result.append(
                ProvenanceRecord(
                    claim_id=claim_id,
                    evidence_ids=list(dict.fromkeys(_get(raw, "evidence_ids", ()) or [evidence_id])),
                    source_refs=[source_ref],
                    fact_state=FactState(_value(_get(raw, "fact_state"))),
                    disclosure=DisclosureLevel(_value(_get(raw, "disclosure", _get(raw, "disclosure_level")))),
                    output_mode=output_mode,
                    rendered_claim=rendered_claim,
                    transformations=list(_get(raw, "transformations", ())),
                )
            )
        except (TypeError, ValueError):
            continue
    return result


def build_confirmation_questions(
    records: Sequence[Any],
    constraints: Sequence[Any] = (),
    limit: int = 6,
) -> list[str]:
    """Create bounded questions without exposing excluded or sensitive content."""

    if limit <= 0:
        return []
    questions: list[str] = []
    for record in records:
        fact = str(_value(_get(record, "fact_state", "F5"))).upper()
        disclosure = str(_value(_get(record, "disclosure", _get(record, "disclosure_level", "P3")))).upper()
        claim = str(_get(record, "safe_claim", _get(record, "proposed_claim", ""))).strip()
        freshness = _get(record, "freshness")
        stale = bool(_get(freshness, "stale", False))
        dynamic_unchecked = bool(_get(freshness, "dynamic", False)) and not _get(freshness, "checked_at")
        if disclosure == "P3" or fact == "F6" or detect_sensitive_content(claim):
            continue
        evidence_id = str(_get(record, "evidence_id", _get(record, "candidate_id", "this claim")))
        if fact == "F4":
            questions.append(f"Can you confirm the scope and accuracy of {evidence_id}: {claim}?")
        elif fact == "F5":
            questions.append(f"What owning source can confirm {evidence_id}: {claim}?")
        elif fact == "F3" and (stale or dynamic_unchecked):
            questions.append(f"Is {evidence_id} still current, and when was it last verified: {claim}?")
        if len(questions) >= limit:
            return questions
    for constraint in constraints:
        status = str(_value(_get(constraint, "status", "unknown"))).lower()
        if status != ConstraintStatus.UNKNOWN.value:
            continue
        constraint_id = str(_get(constraint, "constraint_id", "constraint"))
        kind = str(_get(constraint, "kind", "application constraint"))
        questions.append(f"Can you confirm {kind} for {constraint_id} and provide current evidence?")
        if len(questions) >= limit:
            break
    return questions
