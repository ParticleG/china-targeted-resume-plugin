"""Role competency construction facade."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..competencies import build_competencies, merge_role_family_competencies
from ..models import Competency, Requirement


def build_role_competencies(
    requirements: Iterable[Requirement | Mapping[str, Any]],
) -> list[Competency]:
    """Build employer expectations only; candidate evidence is out of scope."""
    return build_competencies(requirements)


def merge_company_delta(
    baseline: Iterable[Competency | Mapping[str, Any]],
    company_delta: Iterable[Competency | Mapping[str, Any]],
    *,
    company_explicit_source_ids: Iterable[str],
) -> list[Competency]:
    return merge_role_family_competencies(
        baseline,
        company_delta,
        company_explicit_source_ids=company_explicit_source_ids,
    )
