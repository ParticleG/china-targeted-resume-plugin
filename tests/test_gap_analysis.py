from __future__ import annotations

import pytest

from china_targeted_resume.application_advice import recommend_application
from china_targeted_resume.evidence import build_evidence_record
from china_targeted_resume.gaps import build_gaps
from china_targeted_resume.models import (
    ApplicationConstraint,
    ApplicationDecision,
    ConstraintStatus,
    ExperienceDurationNearMatchDiagnostic,
    GapSeverity,
    RoleMatchState,
)


def test_gap_severity_is_orthogonal_to_five_state(requirement_factory, mapping_factory) -> None:
    requirements = [
        requirement_factory(requirement_id="REQ-CRITICAL", hard_gate=True, priority="critical"),
        requirement_factory(
            requirement_id="REQ-MAJOR",
            necessity="required",
            hard_gate=False,
            priority="medium",
        ),
        requirement_factory(
            requirement_id="REQ-MINOR",
            necessity="preferred",
            hard_gate=False,
            priority="low",
        ),
    ]
    mappings = [
        mapping_factory(requirement_id="REQ-CRITICAL", match_state=RoleMatchState.KNOWLEDGE_WITHOUT_PRACTICE),
        mapping_factory(requirement_id="REQ-MAJOR", match_state=RoleMatchState.CLEAR_GAP),
        mapping_factory(requirement_id="REQ-MINOR", match_state=RoleMatchState.CLEAR_GAP),
    ]

    gaps = build_gaps(requirements, mappings)

    assert [(gap.match_state, gap.severity) for gap in gaps] == [
        (RoleMatchState.KNOWLEDGE_WITHOUT_PRACTICE, GapSeverity.CRITICAL),
        (RoleMatchState.CLEAR_GAP, GapSeverity.MAJOR),
        (RoleMatchState.CLEAR_GAP, GapSeverity.MINOR),
    ]


def test_pending_confirmation_has_null_severity_and_direction(requirement_factory, mapping_factory) -> None:
    [gap] = build_gaps(
        [requirement_factory(hard_gate=True)],
        [mapping_factory(match_state=RoleMatchState.PENDING_CONFIRMATION)],
    )

    assert gap.match_state is RoleMatchState.PENDING_CONFIRMATION
    assert gap.severity is None
    assert gap.validation_direction
    assert "unknown" in gap.job_impact.casefold()


def test_direct_evidence_does_not_mechanically_create_gap(requirement_factory, mapping_factory) -> None:
    mapping = mapping_factory(
        match_state=RoleMatchState.DIRECT_EVIDENCE,
        evidence_ids=["ev-direct"],
    )
    assert build_gaps([requirement_factory()], [mapping]) == []


def test_hard_constraint_is_not_averaged_with_strong_evidence(requirement_factory, mapping_factory, dossier_factory) -> None:
    mappings = [
        mapping_factory(
            requirement_id=f"REQ-{index}",
            match_state=RoleMatchState.DIRECT_EVIDENCE,
            evidence_ids=[f"ev-{index}"],
        )
        for index in range(10)
    ]
    constraint = ApplicationConstraint(
        constraint_id="constraint-location",
        kind="location",
        hard_gate=True,
        status=ConstraintStatus.UNSATISFIED,
        required_value="Synthetic City",
        candidate_value="Different Synthetic City",
    )

    recommendation = recommend_application(
        dossier_factory().target_context,
        mappings,
        [],
        [constraint],
        include_numeric=True,
    )

    assert recommendation.decision is ApplicationDecision.DEPRIORITIZE
    assert recommendation.hard_constraint_readiness == "blocked"
    assert recommendation.evidence_strength == "strong"
    assert recommendation.numeric_diagnostic is not None
    assert recommendation.numeric_diagnostic.score == pytest.approx(1.0)
    assert any("independently" in reason.casefold() for reason in recommendation.rationale)

def test_experience_and_skill_thresholds_cannot_be_application_constraints() -> None:
    for kind in ("experience", "experience_duration", "skills"):
        with pytest.raises(
            ValueError,
            match="belong to explicit requirements",
        ):
            ApplicationConstraint(
                constraint_id=f"constraint-{kind}",
                kind=kind,
                hard_gate=False,
                status=ConstraintStatus.UNSATISFIED,
            )


def _candidate_duration_record(
    candidate_factory,
    requirement,
    years,
):
    candidate = candidate_factory(
        candidate_id=f"candidate-{requirement.requirement_id}-{years}",
        requirement_ids=[requirement.requirement_id],
        proposed_claim=(
            f"Maintained {years} years of professional Python development "
            "experience; checked 2026-08-30."
        ),
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
    )
    record = build_evidence_record(
        candidate,
        [requirement.requirement_id],
        mode="targeted_application",
    )
    assert record is not None
    return record


def test_structured_explicit_requirement_shortfall_is_disclosed_as_near_match(
    requirement_factory,
    mapping_factory,
    dossier_factory,
    candidate_factory,
) -> None:
    requirement = requirement_factory(
        requirement_id="REQ-PYTHON-YEARS",
        text="At least 5 years of professional Python development experience.",
        verbatim_quote="At least 5 years of professional Python development experience.",
        experience_duration={
            "scope": "professional Python development",
            "required_min_years": 5,
        },
    )
    record = _candidate_duration_record(
        candidate_factory,
        requirement,
        4,
    )
    mapping = mapping_factory(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=[record.evidence_id],
        experience_duration_diagnostic=ExperienceDurationNearMatchDiagnostic(
            candidate_scope="professional Python development",
            required_scope="Professional Python development",
            candidate_years=4,
            required_min_years=5,
            evidence_refs=[record.evidence_id],
            checked_at="2026-08-30T00:00:00Z",
        ),
    )

    recommendation = recommend_application(
        dossier_factory().target_context,
        [mapping],
        [],
        [],
        requirements=[requirement],
        records=[record],
    )

    assert recommendation.decision is ApplicationDecision.APPLY_WITH_RISKS
    assert recommendation.hard_constraint_readiness == "not_applicable"
    assert recommendation.near_match_requirements == [
        "REQ-PYTHON-YEARS"
    ]
    assert any("20.0%" in reason for reason in recommendation.rationale)
    assert any(
        f"evidence={record.evidence_id}" in reason
        and "checked_at=2026-08-30" in reason
        and "do not present it as satisfied" in reason.casefold()
        for reason in recommendation.rationale
    )

def test_structured_duration_shortfall_over_25_percent_is_not_near_match(
    requirement_factory,
    mapping_factory,
    dossier_factory,
    candidate_factory,
) -> None:
    requirement = requirement_factory(
        requirement_id="REQ-PYTHON-SENIOR",
        text="At least 5 years of professional Python development experience.",
        verbatim_quote="At least 5 years of professional Python development experience.",
        experience_duration={
            "scope": "professional Python development",
            "required_min_years": 5,
        },
    )
    record = _candidate_duration_record(
        candidate_factory,
        requirement,
        3,
    )
    mapping = mapping_factory(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=[record.evidence_id],
        experience_duration_diagnostic={
            "candidate_scope": "professional Python development",
            "required_scope": "professional Python development",
            "candidate_years": 3,
            "required_min_years": 5,
            "evidence_refs": [record.evidence_id],
            "checked_at": "2026-08-30T00:00:00Z",
        },
    )

    recommendation = recommend_application(
        dossier_factory().target_context,
        [mapping],
        [],
        [],
        requirements=[requirement],
        records=[record],
    )

    assert recommendation.near_match_requirements == []


@pytest.mark.parametrize(
    "scope",
    ["Java/Go", "Java, Go", "Java and Go", "Java、Go", "Java 与 Go"],
)
def test_compound_duration_scope_is_rejected_even_when_both_sides_match(
    scope,
) -> None:
    with pytest.raises(ValueError, match="one atomic comparison object"):
        ExperienceDurationNearMatchDiagnostic(
            candidate_scope=scope,
            required_scope=scope,
            candidate_years=4,
            required_min_years=5,
            evidence_refs=["ev-duration"],
            checked_at="2026-08-30T00:00:00Z",
        )


@pytest.mark.parametrize(
    "diagnostic",
    [
        {
            "candidate_scope": "professional Java development",
            "required_scope": "professional Java development",
            "candidate_years": 4,
            "required_min_years": 5,
            "evidence_refs": [],
            "checked_at": "2026-08-30T00:00:00Z",
        },
        {
            "candidate_scope": "professional Java development",
            "required_scope": "professional Java development",
            "candidate_years": 4,
            "required_min_years": 5,
            "evidence_refs": ["ev-duration"],
        },
    ],
)
def test_duration_diagnostic_requires_evidence_and_check_time(
    mapping_factory,
    diagnostic,
) -> None:
    with pytest.raises(ValueError):
        mapping_factory(
            match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
            evidence_ids=["ev-duration"],
            experience_duration_diagnostic=diagnostic,
        )


def test_duration_diagnostic_rejects_scope_mismatch_and_unselected_evidence(
    mapping_factory,
) -> None:
    with pytest.raises(ValueError, match="same comparison object"):
        ExperienceDurationNearMatchDiagnostic(
            candidate_scope="total software experience",
            required_scope="professional Java development",
            candidate_years=4,
            required_min_years=5,
            evidence_refs=["ev-duration"],
            checked_at="2026-08-30T00:00:00Z",
        )

    with pytest.raises(
        ValueError,
        match="must be selected mapping evidence_ids",
    ):
        mapping_factory(
            match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
            evidence_ids=["ev-other"],
            experience_duration_diagnostic={
                "candidate_scope": "professional Java development",
                "required_scope": "professional Java development",
                "candidate_years": 4,
                "required_min_years": 5,
                "evidence_refs": ["ev-duration"],
                "checked_at": "2026-08-30T00:00:00Z",
            },
        )


def test_free_text_values_do_not_create_requirement_near_match(
    requirement_factory,
    mapping_factory,
    dossier_factory,
) -> None:
    requirement = requirement_factory(
        requirement_id="REQ-COMPOUND-YEARS",
        text="Five years Java and eight years total experience.",
        verbatim_quote="Five years Java and eight years total experience.",
    )
    mapping = mapping_factory(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=["ev-general"],
    )

    recommendation = recommend_application(
        dossier_factory().target_context,
        [mapping],
        [],
        [],
        requirements=[requirement],
    )

    assert recommendation.near_match_requirements == []

def test_inferred_requirement_cannot_receive_duration_near_match(
    requirement_factory,
    mapping_factory,
    dossier_factory,
) -> None:
    requirement = requirement_factory(
        requirement_id="REQ-INFERRED-YEARS",
        origin="inferred",
        verbatim_quote=None,
        source_span=None,
        inference_basis="Company-level role-family pattern only.",
        hard_gate=False,
    )
    mapping = mapping_factory(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=["ev-duration"],
        experience_duration_diagnostic={
            "candidate_scope": "professional Python development",
            "required_scope": "professional Python development",
            "candidate_years": 4,
            "required_min_years": 5,
            "evidence_refs": ["ev-duration"],
            "checked_at": "2026-08-30T00:00:00Z",
        },
    )

    recommendation = recommend_application(
        dossier_factory().target_context,
        [mapping],
        [],
        [],
        requirements=[requirement],
    )

    assert recommendation.near_match_requirements == []

def test_constraint_status_is_independent_from_five_state(mapping_factory, dossier_factory) -> None:
    pending_constraint = ApplicationConstraint(
        constraint_id="constraint-travel",
        kind="travel",
        hard_gate=True,
        status=ConstraintStatus.UNKNOWN,
    )
    direct = mapping_factory(
        match_state=RoleMatchState.DIRECT_EVIDENCE,
        evidence_ids=["ev-direct"],
    )

    recommendation = recommend_application(
        dossier_factory().target_context, [direct], [], [pending_constraint]
    )

    assert recommendation.decision is ApplicationDecision.PENDING_INFORMATION
    assert recommendation.hard_constraint_readiness == "pending"
    assert recommendation.pending_information == ["constraint-travel"]


def test_recommendation_is_multidimensional_not_a_fixed_ratio(requirement_factory, mapping_factory, dossier_factory) -> None:
    requirement = requirement_factory(requirement_id="REQ-RISK", necessity="required")
    mapping = mapping_factory(requirement_id="REQ-RISK", match_state=RoleMatchState.CLEAR_GAP)
    [gap] = build_gaps([requirement], [mapping])

    recommendation = recommend_application(dossier_factory().target_context, [mapping], [gap], [])

    assert recommendation.decision is ApplicationDecision.APPLY_WITH_RISKS
    assert recommendation.major_gaps == [gap.gap_id]
    assert recommendation.numeric_diagnostic is None
    dumped = recommendation.model_dump(mode="json")
    assert "70" not in str(dumped)
    assert "30" not in str(dumped)


def test_numeric_diagnostic_is_explicitly_optional(mapping_factory, dossier_factory) -> None:
    mapping = mapping_factory(match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE)

    hidden = recommend_application(dossier_factory().target_context, [mapping], [], [])
    disclosed = recommend_application(
        dossier_factory().target_context, [mapping], [], [], include_numeric=True
    )

    assert hidden.numeric_diagnostic is None
    assert disclosed.numeric_diagnostic is not None
    assert disclosed.numeric_diagnostic.heuristic is True
    assert disclosed.numeric_diagnostic.calculation
