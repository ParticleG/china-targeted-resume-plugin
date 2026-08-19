from __future__ import annotations

from china_targeted_resume.dossier import refresh_role, write_dossier
from china_targeted_resume.evidence import build_evidence_record, refresh_match
from china_targeted_resume.models import RoleMatchState, SourceRef
from china_targeted_resume.role_analysis import anomaly_sections_by_hash


def test_changed_hash_boundary_reports_only_changed_added_or_removed_sources() -> None:
    assert anomaly_sections_by_hash(
        {"unchanged": "same", "changed": "old", "removed": "gone"},
        {"unchanged": "same", "changed": "new", "added": "fresh"},
    ) == {"changed", "removed", "added"}


def test_refresh_role_noops_when_source_hashes_are_unchanged(
    dossier_factory, requirement_factory
) -> None:
    source = SourceRef(path="jd/current.md", source_hash="same-hash")
    old = dossier_factory(requirements=[requirement_factory()], sources=[source])
    altered_requirement = requirement_factory(text="Changed derived text", verbatim_quote="Changed derived text")
    new = dossier_factory(requirements=[altered_requirement], sources=[source])

    assert refresh_role(old, new) == {}


def test_refresh_role_emits_only_sections_affected_by_changed_hash(
    dossier_factory, requirement_factory
) -> None:
    old_requirement = requirement_factory(source_ref="jd/current.md")
    new_requirement = requirement_factory(
        source_ref="jd/current.md",
        text="Must operate synthetic services and on-call",
        verbatim_quote="Must operate synthetic services and on-call",
    )
    old = dossier_factory(
        requirements=[old_requirement],
        sources=[SourceRef(path="jd/current.md", source_hash="hash-old")],
    )
    new = dossier_factory(
        requirements=[new_requirement],
        sources=[SourceRef(path="jd/current.md", source_hash="hash-new")],
    )

    changed = refresh_role(old, new)

    assert set(changed) == {"requirements"}
    assert "on-call" in changed["requirements"]
    assert "competencies" not in changed
    assert "anomalies" not in changed


def test_refresh_role_preserves_human_content_outside_owned_markers(
    tmp_path, dossier_factory, requirement_factory
) -> None:
    output = tmp_path / "synthetic-refresh-output"
    old = dossier_factory(
        requirements=[requirement_factory(source_ref="jd/current.md")],
        sources=[SourceRef(path="jd/current.md", source_hash="hash-old")],
    )
    new = dossier_factory(
        requirements=[
            requirement_factory(
                source_ref="jd/current.md",
                text="Must support a synthetic on-call rotation",
                verbatim_quote="Must support a synthetic on-call rotation",
            )
        ],
        sources=[SourceRef(path="jd/current.md", source_hash="hash-new")],
    )
    write_dossier(old, output, job_description="Synthetic source JD")
    owner = output / "requirement-analysis.md"
    human_note = "\nHuman conclusion: verify the rotation boundary.\n"
    owner.write_text(owner.read_text(encoding="utf-8") + human_note, encoding="utf-8")

    refresh_role(old, new, output_dir=output)
    refreshed = owner.read_text(encoding="utf-8")

    assert "Must support a synthetic on-call rotation" in refreshed
    assert refreshed.endswith(human_note)


def test_refresh_match_recomputes_only_requirements_owned_by_changed_personal_hash(
    requirement_factory, candidate_factory, mapping_factory
) -> None:
    requirements = [
        requirement_factory(requirement_id="REQ-A"),
        requirement_factory(requirement_id="REQ-B", text="Know Rust", verbatim_quote="Know Rust"),
    ]
    candidate_a = candidate_factory(
        candidate_id="candidate-a",
        requirement_ids=["REQ-A"],
        source=SourceRef(
            path="personal-data/work/orbit-orchard-experience.md",
            title="Orbit Orchard",
            section="Reliability contribution",
            source_hash="hash-changed",
            source_type="career-source",
        ),
    )
    evidence_a = build_evidence_record(candidate_a, ["REQ-A"], mode="targeted_application")
    assert evidence_a is not None
    previous_a = mapping_factory(
        requirement_id="REQ-A", match_state=RoleMatchState.PENDING_CONFIRMATION
    )
    previous_b = mapping_factory(
        requirement_id="REQ-B", match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE
    )

    result = refresh_match(
        [previous_a, previous_b],
        requirements,
        [evidence_a],
        ["hash-changed"],
    )

    assert result.refreshed_requirement_ids == ["REQ-A"]
    assert result.unchanged_requirement_ids == ["REQ-B"]
    by_id = {mapping.requirement_id: mapping for mapping in result.mappings}
    assert by_id["REQ-A"].match_state is RoleMatchState.DIRECT_EVIDENCE
    assert by_id["REQ-B"] == previous_b


def test_refresh_match_ignores_changed_company_research_hash(
    requirement_factory, mapping_factory
) -> None:
    requirement = requirement_factory()
    previous = mapping_factory(match_state=RoleMatchState.CLEAR_GAP)

    result = refresh_match(
        [previous],
        [requirement],
        [],
        {"company-research/acme.md": "company-hash"},
    )

    assert result.refreshed_requirement_ids == []
    assert result.unchanged_requirement_ids == [requirement.requirement_id]
    assert result.mappings == [previous]
