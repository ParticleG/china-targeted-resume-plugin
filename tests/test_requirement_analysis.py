from __future__ import annotations

import pytest
from pydantic import ValidationError

from china_targeted_resume.models import Requirement, RequirementNecessity, RequirementOrigin
from china_targeted_resume.role_analysis import parse_job_description
from china_targeted_resume.requirements import (
    keyword_review_signals,
    make_inferred_requirement,
    merge_role_family_requirements,
    parse_requirements,
)


def test_required_and_preferred_language_is_preserved_despite_repetition() -> None:
    jd = """# Required qualifications
- Must know Python.
- Must know Python.

# Preferred qualifications
- Python experience is preferred.
"""
    requirements = parse_requirements(jd, source_id="fixture-jd")

    assert [item.necessity for item in requirements] == [
        RequirementNecessity.REQUIRED,
        RequirementNecessity.REQUIRED,
        RequirementNecessity.PREFERRED,
    ]
    assert [item.hard_gate for item in requirements] == [True, True, False]
    assert requirements[0].text == requirements[1].text
    assert keyword_review_signals(jd, minimum_count=2)


def test_explicit_requirements_retain_verbatim_multiline_quote_and_span() -> None:
    jd = """# Responsibilities
- Operate the queue service
  across two synthetic regions.
# Preferred qualifications
- Rust is a plus.
"""
    responsibilities, preferred = parse_requirements(jd, source_id="fixture-jd")

    assert responsibilities.verbatim_quote == "- Operate the queue service\n  across two synthetic regions."
    assert responsibilities.source_span.start_line == 2
    assert responsibilities.source_span.end_line == 3
    assert responsibilities.origin is RequirementOrigin.EXPLICIT
    assert responsibilities.inference_basis is None
    assert preferred.necessity is RequirementNecessity.PREFERRED


def test_inferred_requirement_has_basis_and_confidence_but_no_quote_or_gate() -> None:
    inferred = make_inferred_requirement(
        "Likely needs incident coordination",
        inference_basis="The role family owns on-call operations.",
        inference_source="role-family/platform.md",
        confidence=0.65,
        requirement_id="REQ-INF-1",
    )

    assert inferred.origin is RequirementOrigin.INFERRED
    assert inferred.inference_basis == "The role family owns on-call operations."
    assert inferred.confidence == 0.65
    assert inferred.verbatim_quote is None
    assert inferred.source_span is None
    assert inferred.hard_gate is False


@pytest.mark.parametrize(
    "updates",
    [
        {"source_span": None},
        {"verbatim_quote": None},
        {"inference_basis": "guessed"},
    ],
)
def test_explicit_requirement_schema_rejects_missing_or_inferred_basis(requirement_factory, updates) -> None:
    payload = requirement_factory().model_dump(mode="python")
    payload.update(updates)
    with pytest.raises(ValidationError):
        Requirement.model_validate(payload)


def test_role_family_baseline_cannot_create_company_hard_gate(requirement_factory) -> None:
    baseline = requirement_factory(
        requirement_id="family",
        source_ref="role-family/platform.md",
        verbatim_quote="Must operate production services",
        source_span={"start_line": 1, "end_line": 1},
        necessity="required",
        hard_gate=True,
    )
    company = requirement_factory(
        requirement_id="company",
        source_ref="company/acme-current-jd.md",
        verbatim_quote="Must join the support rotation",
        text="Must join the support rotation",
        source_span={"start_line": 7, "end_line": 7},
        necessity="required",
        hard_gate=True,
    )

    merged = merge_role_family_requirements(
        [baseline], [company], company_explicit_source_ids=["company/acme-current-jd.md"]
    )

    assert merged[0].necessity is RequirementNecessity.CONTEXT
    assert merged[0].hard_gate is False
    assert merged[1].necessity is RequirementNecessity.REQUIRED
    assert merged[1].hard_gate is True


def test_unapproved_company_delta_cannot_cross_hard_gate_boundary(requirement_factory) -> None:
    delta = requirement_factory(
        source_ref="third-party/role-summary.md",
        verbatim_quote="Must hold a certification",
        text="Must hold a certification",
        source_span={"start_line": 2, "end_line": 2},
        necessity="required",
        hard_gate=True,
    )

    [result] = merge_role_family_requirements([], [delta], company_explicit_source_ids=[])

    assert result.necessity is RequirementNecessity.CONTEXT
    assert result.hard_gate is False


def test_jd_metadata_is_preserved_and_application_instructions_are_not_competencies() -> None:
    jd = """# Platform Engineer

## Source metadata
- Published: 2026-07-10
- Accessed: 2026-07-12
- URL: https://jobs.example.invalid/platform

## Responsibilities
- Must operate production Linux services.

## Application
Applicants must confirm the office-attendance constraint.
"""

    parsed = parse_job_description(jd, source_ref="fixture-jd")

    assert parsed.source_url == "https://jobs.example.invalid/platform"
    assert parsed.published_date is not None
    assert parsed.published_date.isoformat() == "2026-07-10"
    assert parsed.checked_at is not None
    assert parsed.checked_at.isoformat() == "2026-07-12T00:00:00+00:00"
    assert [item.text for item in parsed.requirements] == [
        "Must operate production Linux services."
    ]
