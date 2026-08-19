from __future__ import annotations

import pytest

from china_targeted_resume.application_advice import recommend_application
from china_targeted_resume.gaps import build_gaps
from china_targeted_resume.models import (
    ApplicationConstraint,
    ApplicationDecision,
    ConstraintStatus,
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
