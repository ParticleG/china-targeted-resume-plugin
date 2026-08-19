from __future__ import annotations

from china_targeted_resume.models import Gap, GapSeverity, RoleMatchState, RoadmapHandoffItem
from china_targeted_resume.roadmap_handoff import export_roadmap_handoff


def _gap(
    gap_id: str,
    *,
    state: RoleMatchState = RoleMatchState.CLEAR_GAP,
    severity: GapSeverity | None = GapSeverity.MAJOR,
    reason: str = "Required production evidence is absent.",
) -> Gap:
    return Gap(
        gap_id=gap_id,
        requirement_id=f"REQ-{gap_id}",
        match_state=state,
        severity=severity,
        job_impact="Synthetic role delivery risk",
        reason=reason,
        baseline_evidence_refs=["ev-baseline"],
        validation_direction=["Build and verify a synthetic artifact"],
        roadmap_refs=["role/acme-platform"],
    )


def test_handoff_requires_explicit_request() -> None:
    assert export_roadmap_handoff([_gap("major")]) == []
    assert export_roadmap_handoff([_gap("major")], explicitly_requested=False) == []


def test_handoff_excludes_pending_direct_and_minor_preferred_items() -> None:
    gaps = [
        _gap("pending", state=RoleMatchState.PENDING_CONFIRMATION, severity=None),
        _gap("minor", severity=GapSeverity.MINOR, reason="Preferred bonus qualification is absent."),
        _gap("major"),
    ]

    exported = export_roadmap_handoff(
        gaps,
        explicitly_requested=True,
        severities=["Critical", "Major", "Minor"],
    )

    assert [item.gap_id for item in exported] == ["major"]


def test_handoff_copies_baseline_state_and_never_elevates_it() -> None:
    source = _gap(
        "knowledge",
        state=RoleMatchState.KNOWLEDGE_WITHOUT_PRACTICE,
        severity=GapSeverity.CRITICAL,
    )

    [item] = export_roadmap_handoff([source], explicitly_requested=True)

    assert item.match_state is RoleMatchState.KNOWLEDGE_WITHOUT_PRACTICE
    assert item.baseline_evidence_refs == source.baseline_evidence_refs
    assert item.requirement_id == source.requirement_id
    assert item.source_role_refs == [
        "role-dossier/gap-analysis.md#knowledge"
    ]
    assert item.suggested_artifacts == [
        "reproducible implementation artifact",
        "automated test or validation record",
        "technical design and verification report",
    ]
    assert item.target_owning_file == "personal-data/personal-projects/knowledge.md"


def test_roadmap_item_schema_rejects_elevated_direct_or_pending_state() -> None:
    base = {
        "gap_id": "gap-1",
        "requirement_id": "REQ-1",
        "severity": "Major",
        "priority_reason": "Major job impact",
        "target_capability": "Synthetic production skill",
        "target_owning_file": "roadmap/handoffs/gap-1.json",
    }
    for state in (RoleMatchState.DIRECT_EVIDENCE, RoleMatchState.PENDING_CONFIRMATION):
        try:
            RoadmapHandoffItem.model_validate(base | {"match_state": state})
        except ValueError:
            pass
        else:
            raise AssertionError(f"roadmap accepted prohibited state {state.value}")
