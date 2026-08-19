"""Multidimensional, auditable application advice."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from china_targeted_resume.models import (
    ApplicationDecision,
    ApplicationRecommendation,
    ConstraintStatus,
    EvidenceMapping,
    Gap,
    GapSeverity,
    JdCompleteness,
    NumericDiagnostic,
    RoleMatchState,
    TargetBasis,
)


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _constraint_status(constraint: Any) -> ConstraintStatus | None:
    try:
        return ConstraintStatus(_value(_get(constraint, "status")))
    except (TypeError, ValueError):
        return None


def _numeric(mappings: Sequence[EvidenceMapping]) -> NumericDiagnostic:
    state_values = {
        RoleMatchState.DIRECT_EVIDENCE: 1.0,
        RoleMatchState.TRANSFERABLE_EXPERIENCE: 0.65,
        RoleMatchState.KNOWLEDGE_WITHOUT_PRACTICE: 0.35,
        RoleMatchState.CLEAR_GAP: 0.0,
    }
    weights = {
        mapping.requirement_id: max(float(mapping.resume_priority), 0.01)
        for mapping in mappings
    }
    unknowns = [
        mapping.requirement_id
        for mapping in mappings
        if mapping.match_state == RoleMatchState.PENDING_CONFIRMATION
    ]
    known = [mapping for mapping in mappings if mapping.requirement_id not in unknowns]
    denominator = sum(weights[mapping.requirement_id] for mapping in known)
    if denominator <= 0:
        denominator = sum(weights.values()) or 1.0
        score = None
        calculation = "No confirmed mapping states; score is null."
    else:
        numerator = sum(weights[m.requirement_id] * state_values[m.match_state] for m in known)
        score = numerator / denominator
        calculation = (
            "sum(requirement_weight * diagnostic_state_value) / sum(known requirement weights); "
            f"numerator={numerator:.6f}, denominator={denominator:.6f}. Pending states are excluded."
        )
    return NumericDiagnostic(
        score=score,
        weights=weights,
        denominator=denominator,
        unknowns=unknowns,
        calculation=calculation,
        heuristic=True,
    )


def recommend_application(
    target: Any,
    mappings: Sequence[Any],
    gaps: Sequence[Any],
    constraints: Sequence[Any],
    *,
    include_numeric: bool = False,
) -> ApplicationRecommendation:
    """Explain a decision using target quality, constraints, evidence, and gaps."""

    canonical_mappings = [
        item if isinstance(item, EvidenceMapping) else EvidenceMapping.model_validate(item) for item in mappings
    ]
    canonical_gaps = [item if isinstance(item, Gap) else Gap.model_validate(item) for item in gaps]
    hard_constraints = [item for item in constraints if bool(_get(item, "hard_gate", False))]
    hard_unsatisfied = [item for item in hard_constraints if _constraint_status(item) == ConstraintStatus.UNSATISFIED]
    hard_unknown = [
        item
        for item in hard_constraints
        if _constraint_status(item) in {None, ConstraintStatus.UNKNOWN}
    ]
    applicable_hard = [
        item for item in hard_constraints if _constraint_status(item) != ConstraintStatus.NOT_APPLICABLE
    ]
    if hard_unsatisfied:
        hard_readiness = "blocked"
    elif hard_unknown:
        hard_readiness = "pending"
    elif applicable_hard:
        hard_readiness = "ready"
    else:
        hard_readiness = "not_applicable"

    completeness = JdCompleteness(_value(_get(target, "jd_completeness", JdCompleteness.UNAVAILABLE)))
    basis = TargetBasis(_value(_get(target, "target_basis", TargetBasis.INSUFFICIENT_TARGET)))
    critical = [gap.gap_id for gap in canonical_gaps if gap.severity == GapSeverity.CRITICAL]
    major = [gap.gap_id for gap in canonical_gaps if gap.severity == GapSeverity.MAJOR]
    pending = [gap.requirement_id for gap in canonical_gaps if gap.severity is None]
    pending.extend(str(_get(item, "constraint_id", "unknown-constraint")) for item in hard_unknown)
    rationale: list[str] = []

    if basis == TargetBasis.INSUFFICIENT_TARGET or completeness != JdCompleteness.COMPLETE:
        decision = ApplicationDecision.PENDING_INFORMATION
        rationale.append("Target information is incomplete or stale; gather a current target before deciding.")
    elif hard_unsatisfied:
        decision = ApplicationDecision.DEPRIORITIZE
        rationale.append("At least one independently evaluated hard constraint is unsatisfied.")
    elif hard_unknown:
        decision = ApplicationDecision.PENDING_INFORMATION
        rationale.append("At least one hard constraint is unknown and must be confirmed independently.")
    elif critical or major:
        decision = ApplicationDecision.APPLY_WITH_RISKS
        rationale.append("Confirmed gaps exist; applying remains a judgment with explicit interview risks.")
    elif pending:
        decision = ApplicationDecision.PENDING_INFORMATION
        rationale.append("Material personal evidence remains pending confirmation.")
    else:
        decision = ApplicationDecision.APPLY_NOW
        rationale.append("No blocking constraint or confirmed material gap was identified.")

    states = {mapping.match_state for mapping in canonical_mappings}
    if RoleMatchState.DIRECT_EVIDENCE in states and states <= {
        RoleMatchState.DIRECT_EVIDENCE,
        RoleMatchState.TRANSFERABLE_EXPERIENCE,
    }:
        strength = "strong"
    elif states & {RoleMatchState.DIRECT_EVIDENCE, RoleMatchState.TRANSFERABLE_EXPERIENCE}:
        strength = "medium"
    elif canonical_mappings and RoleMatchState.PENDING_CONFIRMATION not in states:
        strength = "weak"
    else:
        strength = "unknown"
    rationale.extend(
        [
            f"Hard-constraint readiness: {hard_readiness}.",
            f"Evidence strength: {strength}.",
            f"Critical gaps: {len(critical)}; major gaps: {len(major)}; pending items: {len(pending)}.",
        ]
    )

    # Tier B and weaker target bases deliberately carry no percentage coverage.
    coverage = None
    if basis == TargetBasis.EXACT_CURRENT_JD and completeness == JdCompleteness.COMPLETE:
        coverage = _get(target, "explicit_requirement_coverage")

    return ApplicationRecommendation(
        decision=decision,
        target_source_completeness=completeness,
        hard_constraint_readiness=hard_readiness,
        explicit_requirement_coverage=coverage,
        evidence_strength=strength,
        critical_gaps=critical,
        major_gaps=major,
        pending_information=list(dict.fromkeys(pending)),
        rationale=rationale,
        heuristic=True,
        numeric_diagnostic=_numeric(canonical_mappings) if include_numeric else None,
    )
