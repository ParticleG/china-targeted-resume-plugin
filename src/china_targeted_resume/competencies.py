"""Build role competencies from job expectations, never candidate evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from .models import Competency, Requirement

_CANDIDATE_FIELDS = {
    "candidate", "candidate_match", "match", "match_state", "evidence",
    "evidence_ids", "gap", "gap_severity", "score", "coverage",
}


def _dump(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json", exclude_none=False)
    return dict(item)


def _make_competency(data: dict[str, Any]) -> Competency:
    if _CANDIDATE_FIELDS.intersection(data):
        raise ValueError("competencies may describe only job expectations")
    fields = Competency.model_fields
    aliases = {field.alias: name for name, field in fields.items() if field.alias}
    selected: dict[str, Any] = {}
    for key, value in data.items():
        target = key if key in fields else aliases.get(key)
        if target is not None and target not in _CANDIDATE_FIELDS:
            selected[target] = value
    return Competency.model_validate(selected)


def _clean_expectation(text: str) -> str:
    return re.sub(r"^\s*(?:[-*•·]|\d+[.)、])\s+", "", text).strip()


def build_competencies(
    requirements: Iterable[Requirement | Mapping[str, Any]],
) -> list[Competency]:
    """Create one stable job-expectation competency per requirement.

    Consolidation is intentionally conservative: different source statements
    remain traceable instead of being merged merely because they share words.
    """
    result: list[Competency] = []
    for ordinal, requirement in enumerate(requirements, 1):
        record = _dump(requirement)
        rid = str(record.get("id") or record.get("requirement_id") or f"REQ-{ordinal:03d}")
        expectation = _clean_expectation(str(
            record.get("text") or record.get("summary") or record.get("quote") or rid
        ))
        cid = f"COMP-{ordinal:03d}"
        necessity = str(record.get("necessity", "unknown"))
        depth = {
            "required": "independent delivery",
            "preferred": "working familiarity",
            "responsibility": "demonstrated execution",
            "context": "contextual understanding",
        }.get(necessity, "level not specified")
        source_ref = record.get("source_ref")
        origin = str(record.get("origin", "explicit"))
        result.append(_make_competency({
            "competency_id": cid,
            "requirement_ids": [rid],
            "dimension": expectation,
            "expected_depth": depth,
            "responsibility_scope": expectation
                if necessity == "responsibility" else None,
            "validation_signals": [f"Can explain and apply: {expectation}"],
            "origin": origin,
            "inference_basis": record.get("inference_basis"),
            "confidence": record.get("confidence", 1.0),
            "source_refs": [source_ref] if source_ref else [],
        }))
    return result


def merge_role_family_competencies(
    baseline: Iterable[Competency | Mapping[str, Any]],
    company_delta: Iterable[Competency | Mapping[str, Any]],
    *,
    company_explicit_source_ids: Iterable[str],
) -> list[Competency]:
    """Merge a role-family baseline with a company-specific delta.

    Baseline entries can establish generic expectations only. A company-level
    Required classification or hard gate survives only when at least one of
    its sources is explicitly identified as a company source.
    """
    explicit_sources = set(company_explicit_source_ids)
    merged: dict[str, dict[str, Any]] = {}

    def identity(record: Mapping[str, Any]) -> str:
        return str(record.get("dimension") or record.get("competency_id")).casefold()

    for item in baseline:
        record = _dump(item)
        record.pop("candidate_match", None)
        record.pop("evidence_ids", None)
        record.pop("hard_gate", None)
        record.pop("necessity", None)
        merged[identity(record)] = record

    for item in company_delta:
        delta = _dump(item)
        delta.pop("candidate_match", None)
        delta.pop("evidence_ids", None)
        source_ids = set(delta.get("source_refs") or delta.get("source_ids") or [])
        is_company_explicit = bool(source_ids & explicit_sources) and str(
            delta.get("origin", "explicit")
        ) == "explicit"
        if not is_company_explicit and delta.get("origin") != "explicit":
            delta.setdefault("inference_basis", "Role-family baseline or non-company source")
        key = identity(delta)
        if key in merged:
            base = merged[key]
            requirement_ids = list(dict.fromkeys((base.get("requirement_ids") or []) + (delta.get("requirement_ids") or [])))
            combined_sources = list(dict.fromkeys((base.get("source_refs") or []) + (delta.get("source_refs") or [])))
            base.update({k: v for k, v in delta.items() if v is not None})
            base["requirement_ids"] = requirement_ids
            base["source_refs"] = combined_sources
            merged[key] = base
        else:
            merged[key] = delta

    result: list[Competency] = []
    for ordinal, record in enumerate(merged.values(), 1):
        record["competency_id"] = f"COMP-{ordinal:03d}"
        sanitized = {key: value for key, value in record.items() if key not in _CANDIDATE_FIELDS}
        result.append(_make_competency(sanitized))
    return result
