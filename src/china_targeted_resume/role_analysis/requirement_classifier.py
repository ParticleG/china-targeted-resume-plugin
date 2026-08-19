"""Requirement classification rules independent of keyword frequency."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Requirement
from ..requirements import make_inferred_requirement


def classify_requirement(requirement: Requirement) -> Requirement:
    """Validate invariants and return the canonical requirement unchanged.

    Explicit Required/Preferred/responsibility labels have already been derived
    from their quote/section by the parser. This stage deliberately does not
    inspect corpus frequency.
    """
    if str(requirement.origin) == "inferred" and requirement.hard_gate:
        raise ValueError("inferred requirements cannot be hard gates")
    if str(requirement.origin) == "explicit":
        if not requirement.verbatim_quote or requirement.source_span is None:
            raise ValueError("explicit requirements require quote and line span")
    return requirement


def classify_requirements(requirements: Iterable[Requirement]) -> list[Requirement]:
    return [classify_requirement(item) for item in requirements]


def infer_requirement(
    text: str,
    *,
    basis: str,
    source_ref: str,
    confidence: float,
    requirement_id: str,
    category: str = "domain",
) -> Requirement:
    """Create a traceable, non-gating inferred requirement."""
    return make_inferred_requirement(
        text,
        inference_basis=basis,
        inference_source=source_ref,
        confidence=confidence,
        requirement_id=requirement_id,
        category=category,
    )
