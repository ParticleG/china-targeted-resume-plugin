from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from china_targeted_resume.evidence import (
    build_evidence_map,
    build_evidence_record,
    claim_supports_skill,
    detect_metric_qualifiers,
)
from china_targeted_resume.models import EvidenceMapping, RoleMatchState, SourceRef
from china_targeted_resume.provenance import build_provenance


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
