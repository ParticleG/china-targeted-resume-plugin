from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from china_targeted_resume.evidence import (
    assess_experience_duration_near_match,
    bind_experience_duration_diagnostics,
    build_evidence_map,
    build_evidence_record,
    claim_supports_skill,
    detect_metric_qualifiers,
)
from china_targeted_resume.models import EvidenceMapping, RoleMatchState, SourceRef
from china_targeted_resume.provenance import build_provenance
from china_targeted_resume.requirements import parse_requirements


@pytest.mark.parametrize("state", list(RoleMatchState))
def test_five_state_round_trip_uses_exact_canonical_values(state: RoleMatchState) -> None:
    payload = {
        "requirement_id": "REQ-STATE",
        "match_state": state.value,
        "evidence_ids": ["ev-1"] if state is RoleMatchState.DIRECT_EVIDENCE else [],
        "selection_reason": "Synthetic state round trip",
    }
    mapping = EvidenceMapping.model_validate(payload)

    assert mapping.match_state is state
    assert mapping.model_dump(mode="json")["match_state"] == state.value


@pytest.mark.parametrize("invalid", ["direct", "no evidence", "unknown", "已有证据", ""])
def test_five_state_schema_rejects_noncanonical_values(invalid: str) -> None:
    with pytest.raises(ValidationError):
        EvidenceMapping.model_validate(
            {
                "requirement_id": "REQ-STATE",
                "match_state": invalid,
                "selection_reason": "Synthetic invalid state",
            }
        )

def _duration_record(
    candidate_factory,
    requirement,
    *,
    years: int,
    claim: str | None = None,
):
    candidate = candidate_factory(
        candidate_id=f"candidate-duration-{years}",
        requirement_ids=[requirement.requirement_id],
        proposed_claim=(
            claim
            or (
                f"Maintained {years} years of professional Python development "
                "experience; checked 2026-08-30."
            )
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


def test_duration_binding_uses_verbatim_requirement_and_owning_candidate_fact(
    candidate_factory,
) -> None:
    [requirement] = parse_requirements(
        "# Required\n"
        "- At least 8 years of professional Python development experience.\n",
        source_id="fixture-jd",
    )
    record = _duration_record(
        candidate_factory,
        requirement,
        years=6,
    )
    mapping = EvidenceMapping(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=[record.evidence_id],
        selection_reason="Verified duration evidence.",
    )
    binding = {
        "requirement_id": requirement.requirement_id,
        "diagnostic": {
            "candidate_scope": "professional Python development",
            "required_scope": "professional Python development",
            "unit": "years",
            "candidate_years": 6,
            "required_min_years": 8,
            "evidence_refs": [record.evidence_id],
            "checked_at": "2026-08-30T00:00:00Z",
        },
    }

    [bound] = bind_experience_duration_diagnostics(
        [mapping],
        [requirement],
        [record],
        [binding],
    )

    assert record.experience_duration_fact is not None
    assert bound.experience_duration_diagnostic is not None
    assert assess_experience_duration_near_match(
        bound,
        requirement,
        [record],
    ) == (6.0, 8.0, 0.25)


def test_duration_binding_rejects_threshold_different_from_verbatim_requirement(
    candidate_factory,
) -> None:
    [requirement] = parse_requirements(
        "# Required\n"
        "- At least 8 years of professional Python development experience.\n",
        source_id="fixture-jd",
    )
    record = _duration_record(
        candidate_factory,
        requirement,
        years=4,
    )
    mapping = EvidenceMapping(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=[record.evidence_id],
        selection_reason="Verified duration evidence.",
    )

    with pytest.raises(
        ValueError,
        match="must match the verbatim requirement",
    ):
        bind_experience_duration_diagnostics(
            [mapping],
            [requirement],
            [record],
            [
                {
                    "requirement_id": requirement.requirement_id,
                    "diagnostic": {
                        "candidate_scope": "professional Python development",
                        "required_scope": "professional Python development",
                        "unit": "years",
                        "candidate_years": 4,
                        "required_min_years": 5,
                        "evidence_refs": [record.evidence_id],
                        "checked_at": "2026-08-30T00:00:00Z",
                    },
                }
            ],
        )


@pytest.mark.parametrize(
    ("claim", "candidate_years", "expected_error"),
    [
        (
            "Implemented professional Python automation; checked 2026-08-30.",
            4,
            "no owning duration fact",
        ),
        (
            "Maintained 6 years of professional Python development experience; checked 2026-08-30.",
            4,
            "does not match owning evidence",
        ),
        (
            "Maintained 6 years of professional Python development experience.",
            6,
            "no owning duration fact",
        ),
    ],
)
def test_duration_binding_rejects_selected_id_without_matching_candidate_fact(
    candidate_factory,
    claim,
    candidate_years,
    expected_error,
) -> None:
    [requirement] = parse_requirements(
        "# Required\n"
        "- At least 8 years of professional Python development experience.\n",
        source_id="fixture-jd",
    )
    record = _duration_record(
        candidate_factory,
        requirement,
        years=6,
        claim=claim,
    )
    mapping = EvidenceMapping(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=[record.evidence_id],
        selection_reason="Selected evidence ID.",
    )

    with pytest.raises(ValueError, match=expected_error):
        bind_experience_duration_diagnostics(
            [mapping],
            [requirement],
            [record],
            [
                {
                    "requirement_id": requirement.requirement_id,
                    "diagnostic": {
                        "candidate_scope": "professional Python development",
                        "required_scope": "professional Python development",
                        "unit": "years",
                        "candidate_years": candidate_years,
                        "required_min_years": 8,
                        "evidence_refs": [record.evidence_id],
                        "checked_at": "2026-08-30T00:00:00Z",
                    },
                }
            ],
        )



def test_duration_binding_rejects_fact_without_owning_source_span(
    candidate_factory,
) -> None:
    [requirement] = parse_requirements(
        "# Required\n"
        "- At least 8 years of professional Python development experience.\n",
        source_id="fixture-jd",
    )
    candidate = candidate_factory(
        candidate_id="candidate-duration-no-span",
        requirement_ids=[requirement.requirement_id],
        source_span=None,
        proposed_claim=(
            "Maintained 6 years of professional Python development "
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
    assert record.experience_duration_fact is None
    mapping = EvidenceMapping(
        requirement_id=requirement.requirement_id,
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
        evidence_ids=[record.evidence_id],
        selection_reason="Selected evidence without an owning span.",
    )

    with pytest.raises(ValueError, match="no owning duration fact"):
        bind_experience_duration_diagnostics(
            [mapping],
            [requirement],
            [record],
            [
                {
                    "requirement_id": requirement.requirement_id,
                    "diagnostic": {
                        "candidate_scope": "professional Python development",
                        "required_scope": "professional Python development",
                        "unit": "years",
                        "candidate_years": 6,
                        "required_min_years": 8,
                        "evidence_refs": [record.evidence_id],
                        "checked_at": "2026-08-30T00:00:00Z",
                    },
                }
            ],
        )


def test_duration_requirement_mapping_keeps_owning_duration_evidence(
    candidate_factory,
) -> None:
    [requirement] = parse_requirements(
        "# Required\n"
        "- At least 5 years of professional Python development experience.\n",
        source_id="fixture-jd",
    )
    duration_candidate = candidate_factory(
        candidate_id="candidate-duration-mapping",
        requirement_ids=[requirement.requirement_id],
        proposed_claim=(
            "Maintained 4 years of professional Python development "
            "experience; checked 2026-08-30."
        ),
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
    )
    direct_candidate = candidate_factory(
        candidate_id="candidate-direct-python",
        requirement_ids=[requirement.requirement_id],
        proposed_claim="Implemented professional Python automation.",
        match_state=RoleMatchState.DIRECT_EVIDENCE,
    )
    duration_record = build_evidence_record(
        duration_candidate,
        [requirement.requirement_id],
        mode="targeted_application",
    )
    assert duration_record is not None

    [mapping] = build_evidence_map(
        [requirement],
        [direct_candidate, duration_candidate],
        mode="targeted_application",
    )

    assert duration_record.evidence_id in mapping.evidence_ids
    assert any(
        "duration" in risk.casefold()
        for risk in mapping.interview_risks
    )

def test_direct_state_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="direct evidence"):
        EvidenceMapping(
            requirement_id="REQ-STATE",
            match_state=RoleMatchState.DIRECT_EVIDENCE,
            selection_reason="Synthetic contradiction",
        )


def test_evidence_record_preserves_contribution_and_every_metric_qualifier(candidate_factory) -> None:
    candidate = candidate_factory(
        proposed_claim="Contributed with the team to a pilot reducing latency by about 20% during 2025."
    )
    record = build_evidence_record(
        candidate,
        candidate.requirement_ids,
        mode="targeted_application",
        now=datetime(2026, 8, 14, tzinfo=UTC),
    )

    assert record is not None
    detected = detect_metric_qualifiers(record.safe_claim)
    assert detected["has_metric"] is True
    assert {"approximate", "stage", "date", "team"} <= set(detected["qualifiers"])
    assert record.contribution_scope.casefold() == "contributed"
    assert {"approximate", "stage", "date", "team"} <= set(record.metric_precision.split(","))
    joined_restrictions = " ".join(record.forbidden_expansions).casefold()
    assert "strengthen" in joined_restrictions
    assert "qualifier" in joined_restrictions
    assert "increase" in joined_restrictions


def test_nonpersonal_company_or_roadmap_sources_never_become_evidence(candidate_factory) -> None:
    for path, source_type in [
        ("company-research/acme-cloudworks/README.md", "company-research"),
        ("growth-roadmap/platform.md", "growth-roadmap"),
    ]:
        candidate = candidate_factory(
            source=SourceRef(
                path=path,
                title="Synthetic nonpersonal source",
                section="Expectation",
                source_hash="fixture-hash",
                source_type=source_type,
            )
        )
        assert build_evidence_record(candidate, candidate.requirement_ids, mode="targeted_application") is None


def test_mapping_selects_strongest_eligible_state_and_keeps_all_requirements(
    requirement_factory, candidate_factory
) -> None:
    first = requirement_factory(requirement_id="REQ-A")
    second = requirement_factory(requirement_id="REQ-B", text="Know Rust", verbatim_quote="Know Rust")
    transferable = candidate_factory(
        candidate_id="candidate-transfer",
        requirement_ids=["REQ-A"],
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
    )
    direct = candidate_factory(
        candidate_id="candidate-direct",
        requirement_ids=["REQ-A"],
        match_state=RoleMatchState.DIRECT_EVIDENCE,
    )

    mappings = build_evidence_map(
        [first, second], [transferable, direct], mode="targeted_application"
    )

    assert [item.requirement_id for item in mappings] == ["REQ-A", "REQ-B"]
    assert mappings[0].match_state is RoleMatchState.DIRECT_EVIDENCE
    assert len(mappings[0].evidence_ids) == 1
    assert mappings[1].match_state is RoleMatchState.PENDING_CONFIRMATION
    assert mappings[1].missing_evidence


def test_language_coverage_inventory_does_not_prove_language_use() -> None:
    claim = (
        "开发标准 completion provider，覆盖 TypeScript、JavaScript、Python、"
        "Java、C、C++、Go、Rust 等语言。"
    )

    assert claim_supports_skill(claim, "Go", section="个人工作") is False
    assert claim_supports_skill(claim, "Java", section="个人工作") is False
    assert claim_supports_skill(
        "使用 TypeScript 实现 VS Code completion provider。",
        "TypeScript",
        section="个人工作",
    ) is True


def test_composite_technology_requirement_needs_each_named_direct_anchor(
    requirement_factory,
    candidate_factory,
) -> None:
    text = "熟悉 Kubernetes、Docker、Prometheus、Grafana 等云原生和监控技术。"
    requirement = requirement_factory(
        requirement_id="REQ-COMPOSITE",
        text=text,
        verbatim_quote=text,
    )
    docker = candidate_factory(
        candidate_id="candidate-docker",
        requirement_ids=[requirement.requirement_id],
        proposed_claim="使用 Docker 部署平台服务。",
        match_state=RoleMatchState.DIRECT_EVIDENCE,
    )
    kubernetes = candidate_factory(
        candidate_id="candidate-kubernetes",
        requirement_ids=[requirement.requirement_id],
        proposed_claim="使用 Kubernetes 编排平台服务。",
        match_state=RoleMatchState.DIRECT_EVIDENCE,
    )

    [mapping] = build_evidence_map(
        [requirement],
        [docker, kubernetes],
        mode="targeted_application",
    )

    assert mapping.match_state is RoleMatchState.TRANSFERABLE_EXPERIENCE
    assert mapping.evidence_ids
    assert any("Prometheus, Grafana" in item for item in mapping.missing_evidence)


def test_provenance_is_emitted_only_for_visible_policy_eligible_claim(candidate_factory) -> None:
    candidate = candidate_factory(proposed_claim="Contributed to synthetic queue reliability work.")
    evidence = build_evidence_record(candidate, candidate.requirement_ids, mode="targeted_application")
    assert evidence is not None
    raw = evidence.model_dump(mode="python") | {
        "claim_id": "claim-visible",
        "output_mode": "targeted_application",
        "rendered_claim": evidence.safe_claim,
    }

    provenance = build_provenance([raw], ["claim-visible"])

    assert len(provenance) == 1
    assert provenance[0].claim_id == "claim-visible"
    assert provenance[0].evidence_ids == [evidence.evidence_id]
    assert provenance[0].source_refs == [
        f"{evidence.source.path}#{evidence.source.section}@sha256:{evidence.source.source_hash}"
    ]
    assert build_provenance([raw], ["different-claim"]) == []
