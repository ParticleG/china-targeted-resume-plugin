from __future__ import annotations

import json
from pathlib import Path

import pytest

from china_targeted_resume.ir import (
    ClaimMode,
    DisclosurePolicy,
    FactPolicy,
    EvidenceCandidateIR,
    NormalizedEvidenceInput,
    SourceReference,
    SourceSpan,
    ProposalDomain,
    ProposalOwner,
    SemanticProposal,
    StructuralFlags,
)
from china_targeted_resume.markdown_structure import parse_markdown
from china_targeted_resume.models import ResumeVariant
from china_targeted_resume.pipeline import Pipeline
from china_targeted_resume.validation import IRValidationError, approve_claims


SMOKE_ROOT = Path(__file__).parent / "fixtures_nonstandard" / "nonstandard-repository"


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _source_reference(document: object, block: object) -> SourceReference:
    location = block.location
    flags = block.flags
    path = str(document.path).replace("\\", "/")
    if path.startswith(str(SMOKE_ROOT).replace("\\", "/")):
        path = str(Path(path).relative_to(SMOKE_ROOT)).replace("\\", "/")
    return SourceReference(
        path=path,
        source_hash=document.source_hash,
        span=SourceSpan(
            start_line=location.start_line,
            end_line=location.end_line,
            start_byte=location.start_byte,
            end_byte=location.end_byte,
        ),
        exact_quote=document.exact_text(location),
        structural_flags=StructuralFlags(
            block_kind=_enum_value(block.kind),
            inside_fence=flags.inside_fence,
            inside_blockquote=flags.inside_blockquote,
            inside_html=flags.inside_html,
            is_example=flags.example,
            is_quoted=flags.quoted,
            is_template=flags.inside_template,
            negative_instruction=flags.negative_instruction,
            secret_path=flags.secret_path,
            secret_content=flags.secret_content,
            malformed=flags.malformed,
            effective_fact_policy=FactPolicy(_enum_value(block.effective_fact_state)),
            effective_disclosure_policy=DisclosurePolicy(_enum_value(block.effective_disclosure)),
        ),
        heading_ancestry=list(block.heading_ancestry),
        section_id=block.section_identity,
        block_id=block.identity,
    )


def _find(path: Path, phrase: str) -> tuple[object, object]:
    document = parse_markdown(path, source_root=SMOKE_ROOT)
    for block in document.blocks:
        if phrase in document.exact_text(block.location):
            return document, block
    raise AssertionError(f"fixture phrase not found: {phrase}")


def test_nonstandard_smoke_keeps_uncertain_semantics_pending_and_approves_only_supported_claim() -> None:
    smoke_path = SMOKE_ROOT / "smoke-index.md"
    document, supported_block = _find(smoke_path, "The coordinator documented a repeatable")
    supported_reference = _source_reference(document, supported_block)
    supported = EvidenceCandidateIR(
        evidence_id="evidence.supported-handoff",
        source=supported_reference,
        proposed_claim=supported_reference.exact_quote,
        confidence=0.99,
        reasoning="The claim is an exact quote from an unblocked prose block.",
        claim_mode=ClaimMode.EXTRACTIVE,
    )
    approved = approve_claims(
        NormalizedEvidenceInput(input_id="smoke-supported", candidates=[supported]),
        [],
    )
    assert [claim.approved_safe_claim for claim in approved.claims] == [supported_reference.exact_quote]
    assert approved.claims[0].approval_basis.value == "mechanical"
    assert not any("designed every system" in claim.approved_safe_claim for claim in approved.claims)

    uncertain_document, uncertain_block = _find(smoke_path, "service coordination\"")
    uncertain_reference = _source_reference(uncertain_document, uncertain_block)
    uncertain = EvidenceCandidateIR(
        evidence_id="evidence.uncertain-mapping",
        source=uncertain_reference,
        proposed_claim="Service coordination means end-to-end ownership.",
        confidence=0.42,
        reasoning="The fixture explicitly leaves the semantic scope unresolved.",
        claim_mode=ClaimMode.REVIEWED_SEMANTIC,
        unresolved_questions=["Does coordination include ownership or only facilitation?"],
    )
    with pytest.raises(IRValidationError, match="reviewed-semantic approval requires exactly one"):
        approve_claims(NormalizedEvidenceInput(input_id="smoke-uncertain", candidates=[uncertain]), [])


def test_nonstandard_smoke_rejects_fenced_and_inherited_private_material() -> None:
    cases = (
        (SMOKE_ROOT / "smoke-index.md", "confidential escalation path"),
        (SMOKE_ROOT / "smoke-index.md", "designed every system and eliminated every delay"),
        (SMOKE_ROOT / "projects" / "harbor-ledger.md", "This fenced bullet looks like a claim"),
        (SMOKE_ROOT / "projects" / "harbor-ledger.md", "I documented the handoff checklist"),
    )
    for path, phrase in cases:
        document, block = _find(path, phrase)
        reference = _source_reference(document, block)
        candidate = EvidenceCandidateIR(
            evidence_id="evidence.blocked-" + str(block.identity),
            source=reference,
            proposed_claim=reference.exact_quote,
            confidence=0.9,
            reasoning="This candidate is deliberately blocked by structural context.",
        )
        assert reference.structural_flags.blocked
        with pytest.raises(IRValidationError, match="blocked structural policy"):
            approve_claims(NormalizedEvidenceInput(input_id="smoke-blocked", candidates=[candidate]), [])


def test_nonstandard_smoke_uses_current_default_variants_only() -> None:
    defaults = {
        ResumeVariant.RECRUITER_ONE_PAGE.value,
        ResumeVariant.TECHNICAL_TWO_PAGE.value,
    }
    assert defaults == {"recruiter-one-page", "technical-two-page"}
    assert ResumeVariant.EXTENDED_THREE_PAGE.value not in defaults


def test_nonstandard_smoke_discovers_source_map_and_generates_default_variants(tmp_path: Path) -> None:
    pipeline = Pipeline()
    source_map = pipeline.discover_source_structure(SMOKE_ROOT)
    assert source_map.schema_version == 1
    assert source_map.documents
    assert source_map.sections
    assert source_map.blocks
    assert all(not document.path.startswith("/") for document in source_map.documents)
    persisted = source_map.model_dump(mode="json")
    serialized = repr(persisted)
    assert "source_bytes" not in persisted
    assert "source_body" not in serialized
    assert "confidential escalation path" not in serialized
    assert "F6/P3" not in serialized
    assert "Example-only appendix" not in serialized
    validated = pipeline.validate_source_map(SMOKE_ROOT, source_map)
    assert {section.section_id for section in validated.sections} == {
        section.section_id for section in source_map.sections
    }
    assert {block.block_id for block in validated.blocks} == {
        block.block_id for block in source_map.blocks
    }

    name_document, name_block = _find(
        SMOKE_ROOT / "profile-notes.md",
        "Display label: Example Operator",
    )
    name_reference = _source_reference(name_document, name_block)
    name_proposal = SemanticProposal(
        proposal_id="proposal.profile-name",
        source=name_reference,
        domain=ProposalDomain.EVIDENCE,
        owner=ProposalOwner.CANDIDATE,
        proposed_claim=name_reference.exact_quote,
        confidence=0.99,
        reasoning="The synthetic profile label is an exact extractive claim.",
    )
    organization_document, organization_block = _find(
        SMOKE_ROOT / "profile-notes.md",
        "Organization label: Example Cooperative",
    )
    organization_reference = _source_reference(
        organization_document,
        organization_block,
    )
    organization_proposal = SemanticProposal(
        proposal_id="proposal.placement-organization",
        source=organization_reference,
        domain=ProposalDomain.EVIDENCE,
        owner=ProposalOwner.CANDIDATE,
        proposed_claim=organization_reference.exact_quote,
        confidence=0.99,
        reasoning="The synthetic organization label is an exact extractive claim.",
    )
    document, supported_block = _find(
        SMOKE_ROOT / "smoke-index.md",
        "The coordinator documented a repeatable",
    )
    supported_reference = _source_reference(document, supported_block)
    proposal = SemanticProposal(
        proposal_id="proposal.generated-default",
        source=supported_reference,
        domain=ProposalDomain.EVIDENCE,
        owner=ProposalOwner.CANDIDATE,
        proposed_claim=supported_reference.exact_quote,
        confidence=0.99,
        reasoning="The smoke claim is directly extractive and structurally eligible.",
    )
    title_document, title_block = _find(
        SMOKE_ROOT / "role-brief.md",
        "The role coordinates operational reviews",
    )
    title_reference = _source_reference(title_document, title_block)
    title_proposal = SemanticProposal(
        proposal_id="proposal.placement-title",
        source=title_reference,
        domain=ProposalDomain.EVIDENCE,
        owner=ProposalOwner.CANDIDATE,
        proposed_claim=title_reference.exact_quote,
        confidence=0.99,
        reasoning="The synthetic role title context is an exact extractive claim.",
    )
    source_map = source_map.model_copy(
        update={
            "proposals": [
                name_proposal,
                organization_proposal,
                title_proposal,
                proposal,
            ]
        },
    )
    name_candidate = EvidenceCandidateIR(
        evidence_id="evidence.profile-name",
        proposal_id=name_proposal.proposal_id,
        source=name_reference,
        proposed_claim=name_reference.exact_quote,
        confidence=0.99,
        reasoning="The synthetic profile label is an exact extractive claim.",
    )
    organization_candidate = EvidenceCandidateIR(
        evidence_id="evidence.placement-organization",
        proposal_id=organization_proposal.proposal_id,
        source=organization_reference,
        proposed_claim=organization_reference.exact_quote,
        confidence=0.99,
        reasoning="The synthetic organization label is an exact extractive claim.",
    )
    title_candidate = EvidenceCandidateIR(
        evidence_id="evidence.placement-title",
        proposal_id=title_proposal.proposal_id,
        source=title_reference,
        proposed_claim=title_reference.exact_quote,
        confidence=0.99,
        reasoning="The synthetic role title context is an exact extractive claim.",
    )
    supported = EvidenceCandidateIR(
        evidence_id="evidence.generated-default",
        proposal_id=proposal.proposal_id,
        source=supported_reference,
        proposed_claim=supported_reference.exact_quote,
        confidence=0.99,
        reasoning="The smoke claim is directly extractive and structurally eligible.",
    )
    evidence_input = NormalizedEvidenceInput(
        input_id="smoke-generation",
        candidates=[
            name_candidate,
            organization_candidate,
            title_candidate,
            supported,
        ],
    )
    approved = approve_claims(evidence_input, [])
    generation_payload = {
        "source_root": str(SMOKE_ROOT),
        "output_root": str(tmp_path),
        "source_map": source_map.model_dump(mode="json"),
        "evidence_input": evidence_input.model_dump(mode="json"),
        "approved_claims": approved.model_dump(mode="json"),
        "candidate_profile_claims": {"name": "claim.evidence.profile-name"},
        "claim_placements": [
            {
                "claim_id": "claim.evidence.generated-default",
                "section": "experience",
                "group_id": "smoke-role",
                "order": 0,
                "title_claim_id": "claim.evidence.placement-title",
                "organization_claim_id": "claim.evidence.placement-organization",
            }
        ],
        "review_decisions": [],
        "approved_safe_claims": {},
        "user_confirmations": {},
    }
    generated = pipeline.generate_from_ir(generation_payload)
    summary = generated.summary or {}
    manifest_ref = Path(str(summary["resume_variants"]))
    assert manifest_ref.name == "resume-variants.json"
    manifest = json.loads(manifest_ref.read_text(encoding="utf-8"))
    variant_names = {item["variant"] for item in manifest["variants"]}
    assert variant_names == {"recruiter-one-page", "technical-two-page"}
    assert "extended-three-page" not in variant_names
    for variant in manifest["variants"]:
        document_path = manifest_ref.parent / variant["artifacts"]["document"]
        rendered = json.loads(document_path.read_text(encoding="utf-8"))
        serialized_document = json.dumps(rendered, ensure_ascii=False)
        assert "Approved Evidence" not in serialized_document
        assert "Selected Evidence" not in serialized_document
        assert rendered["experience"]
        assert (
            rendered["experience"][0]["organization"]
            == organization_reference.exact_quote
        )
        assert rendered["experience"][0]["role"] == title_reference.exact_quote
        assert any(
            supported_reference.exact_quote.strip() == bullet["text"]
            for bullet in rendered["experience"][0]["bullets"]
        )
    assert any(path.name == "resume-variants.json" for path in generated.artifacts) or any(
        path.name == "resume-variants.json" for path in tmp_path.rglob("resume-variants.json")
    )
