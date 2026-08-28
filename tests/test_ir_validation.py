from __future__ import annotations

import pytest

from china_targeted_resume.ir import (
    ClaimMode,
    DisclosureAudience,
    DisclosureDecision,
    DisclosurePolicy,
    EvidenceCandidateIR,
    FactPolicy,
    NormalizedEvidenceInput,
    ProposalDomain,
    ProposalOwner,
    ReviewDecision,
    ReviewDecisionIR,
    ReviewKind,
    ReviewOutcome,
    SemanticProposal,
    SourceBlockIR,
    SourceDocumentIR,
    SourceMapIR,
    SourceReference,
    SourceSectionIR,
    SourceSpan,
    StructuralFlags,
)
from china_targeted_resume.markdown_structure import parse_markdown_bytes
from china_targeted_resume.policy import parse_policy_markers
from china_targeted_resume.pipeline import Pipeline
from china_targeted_resume.validation import (
    IRValidationError,
    approve_claims,
    revalidate_evidence_input,
    revalidate_source_map,
)


def test_omitted_ir_policy_metadata_fails_closed() -> None:
    flags = StructuralFlags()
    document = SourceDocumentIR(
        document_id="doc.synthetic",
        path="notes/example.md",
        source_hash="sha256:" + "0" * 64,
    )

    assert flags.effective_fact_policy is FactPolicy.F5
    assert flags.effective_disclosure_policy is DisclosurePolicy.P3
    assert flags.blocked is True
    assert document.document_fact_policy is FactPolicy.F5
    assert document.document_disclosure_policy is DisclosurePolicy.P3


def test_ir_omission_matches_policy_parser_defaults() -> None:
    fact, disclosure = parse_policy_markers("plain text without a policy marker")

    assert fact.value == FactPolicy.F5.value
    assert disclosure.value == DisclosurePolicy.P3.value


def test_discovered_source_map_revalidates_after_private_block_filtering(tmp_path) -> None:
    path = tmp_path / "profile.md"
    path.write_text(
        "# Profile F1 P0\n\n"
        "- Public claim F1 P0\n"
        "- Private claim F6 P3\n",
        encoding="utf-8",
    )

    source_map = Pipeline().discover_source_structure(tmp_path)

    assert len(source_map.sections) == 1
    assert len(source_map.blocks) == 1
    assert source_map.sections[0].block_ids == [source_map.blocks[0].block_id]
    assert revalidate_source_map(source_map, tmp_path) == source_map


def test_revalidation_rejects_forged_f1_p0_flags(tmp_path) -> None:
    data = b"- Led API\n"
    path = tmp_path / "note.md"
    path.write_bytes(data)
    parsed = parse_markdown_bytes(data, path="note.md")
    section = parsed.sections[0]
    block = parsed.blocks[0]

    def span(location) -> SourceSpan:
        return SourceSpan(
            start_line=location.start_line,
            end_line=location.end_line,
            start_byte=location.start_byte,
            end_byte=location.end_byte,
        )

    document = SourceDocumentIR(
        document_id="doc.synthetic",
        path="note.md",
        source_hash=parsed.source_hash,
        validation_warnings=list(parsed.warnings),
    )
    section_ir = SourceSectionIR(
        section_id=section.identity,
        document_id=document.document_id,
        span=span(section.location),
        heading=section.heading,
        heading_ancestry=list(section.heading_ancestry),
        duplicate_index=section.occurrence,
        block_ids=[block.identity],
        structural_flags=StructuralFlags(
            effective_fact_policy=FactPolicy.F5,
            effective_disclosure_policy=DisclosurePolicy.P3,
        ),
    )
    forged_flags = StructuralFlags(
        block_kind=block.kind,
        effective_fact_policy=FactPolicy.F1,
        effective_disclosure_policy=DisclosurePolicy.P0,
    )
    block_ir = SourceBlockIR(
        block_id=block.identity,
        document_id=document.document_id,
        section_id=section.identity,
        span=span(block.location),
        heading_ancestry=list(block.heading_ancestry),
        structural_flags=forged_flags,
    )
    proposal = SemanticProposal(
        proposal_id="proposal.forged",
        source=SourceReference(
            path=document.path,
            source_hash=document.source_hash,
            span=span(block.location),
            exact_quote=parsed.exact_text(block.location),
            section_id=section.identity,
            block_id=block.identity,
            structural_flags=forged_flags,
        ),
        domain=ProposalDomain.PERSONAL,
        owner=ProposalOwner.CANDIDATE,
        proposed_claim="- Led API",
        confidence=1.0,
        reasoning="synthetic forged metadata",
    )
    source_map = SourceMapIR(
        documents=[document],
        sections=[section_ir],
        blocks=[block_ir],
        proposals=[proposal],
    )

    with pytest.raises(IRValidationError, match="effective_(fact|disclosure)_policy"):
        revalidate_source_map(source_map, tmp_path)


def _evidence_origin_fixture(tmp_path):
    data = b"# F1 P0\n\n- Led API\n"
    path = tmp_path / "note.md"
    path.write_bytes(data)
    parsed = parse_markdown_bytes(data, path="note.md")
    block = parsed.blocks[0]
    location = block.location
    span = SourceSpan(
        start_line=location.start_line,
        end_line=location.end_line,
        start_byte=location.start_byte,
        end_byte=location.end_byte,
    )
    flags = StructuralFlags(
        block_kind=block.kind,
        effective_fact_policy=FactPolicy.F1,
        effective_disclosure_policy=DisclosurePolicy.P0,
    )
    reference = SourceReference(
        path="note.md",
        source_hash=parsed.source_hash,
        span=span,
        exact_quote=parsed.exact_text(location),
        heading_ancestry=list(block.heading_ancestry),
        structural_flags=flags,
    )
    proposal = SemanticProposal(
        proposal_id="proposal.origin",
        source=reference,
        domain=ProposalDomain.PERSONAL,
        owner=ProposalOwner.CANDIDATE,
        proposed_claim=reference.exact_quote,
        confidence=1.0,
        reasoning="synthetic origin",
    )
    source_map = SourceMapIR(
        documents=[
            SourceDocumentIR(
                document_id="doc.origin",
                path="note.md",
                source_hash=parsed.source_hash,
                validation_warnings=list(parsed.warnings),
            )
        ],
        proposals=[proposal],
    )
    return path, source_map, reference


def test_evidence_revalidation_rejects_missing_origin_proposal(tmp_path) -> None:
    path, source_map, reference = _evidence_origin_fixture(tmp_path)
    candidate = EvidenceCandidateIR(
        evidence_id="evidence.missing-origin",
        proposal_id="proposal.missing",
        source=reference,
        proposed_claim=reference.exact_quote,
        confidence=1.0,
        reasoning="synthetic missing origin",
    )

    with pytest.raises(IRValidationError, match="origin proposal .* missing"):
        revalidate_evidence_input(
            NormalizedEvidenceInput(input_id="evidence-input", candidates=[candidate]),
            source_map,
            path.parent,
        )


def test_evidence_revalidation_rejects_forged_origin_reference(tmp_path) -> None:
    path, source_map, reference = _evidence_origin_fixture(tmp_path)
    forged = reference.model_copy(update={"heading_ancestry": []})
    candidate = EvidenceCandidateIR(
        evidence_id="evidence.forged-origin",
        proposal_id="proposal.origin",
        source=forged,
        proposed_claim=reference.exact_quote,
        confidence=1.0,
        reasoning="synthetic forged origin",
    )

    with pytest.raises(IRValidationError, match="heading ancestry"):
        revalidate_evidence_input(
            NormalizedEvidenceInput(input_id="evidence-input", candidates=[candidate]),
            source_map,
            path.parent,
        )
def _p2_extract_candidate() -> tuple[NormalizedEvidenceInput, ReviewDecisionIR]:
    reference = SourceReference(
        path="note.md",
        source_hash="sha256:" + "0" * 64,
        span=SourceSpan(start_line=1, end_line=1, start_byte=0, end_byte=8),
        exact_quote="Led API",
        structural_flags=StructuralFlags(
            block_kind="paragraph",
            effective_fact_policy=FactPolicy.F1,
            effective_disclosure_policy=DisclosurePolicy.P2,
        ),
    )
    evidence = NormalizedEvidenceInput(
        input_id="evidence-p2",
        candidates=[
            EvidenceCandidateIR(
                evidence_id="evidence.p2",
                source=reference,
                proposed_claim="Led API",
                confidence=1.0,
                reasoning="exact synthetic quote",
                claim_mode=ClaimMode.EXTRACTIVE,
            )
        ],
    )
    reviews = ReviewDecisionIR(
        decisions=[
            ReviewDecision(
                review_id="review.privacy",
                evidence_id="evidence.p2",
                reviewer_id="reviewer.privacy",
                review_kind=ReviewKind.PRIVACY,
                outcome=ReviewOutcome.APPROVE,
                reasoning="P2 allowed for the targeted application",
                approved_safe_claim="Led API",
                disclosure_decision=DisclosureDecision.ALLOWED,
                disclosure_audience=DisclosureAudience.RECRUITER,
                disclosure_purpose="targeted_application",
            )
        ]
    )
    return evidence, reviews


def test_p2_extractive_requires_explicit_user_confirmation() -> None:
    evidence, reviews = _p2_extract_candidate()

    with pytest.raises(IRValidationError, match="P2 extractive approval requires explicit user confirmation"):
        approve_claims(evidence, reviews)
    with pytest.raises(IRValidationError, match="P2 extractive approval requires explicit user confirmation"):
        approve_claims(evidence, reviews, user_confirmations={"evidence.p2": False})


def test_p2_extractive_records_user_confirmation_and_privacy_review() -> None:
    evidence, reviews = _p2_extract_candidate()

    approved = approve_claims(evidence, reviews, user_confirmations={"evidence.p2": True})

    claim = approved.claims[0]
    assert claim.approval_basis.value == "user_confirmed"
    assert claim.reviewer_decision_ids == ["review.privacy"]
    assert claim.approved_safe_claim == "Led API"
@pytest.mark.parametrize(
    ("fact_policy", "message"),
    [
        (FactPolicy.F3, "F3 requires parser-revalidated current freshness proof"),
        (FactPolicy.F4, "fact policy F4 is unapprovable"),
        (FactPolicy.F5, "fact policy F5 is unapprovable"),
    ],
)
def test_unfresh_or_unconfirmed_fact_states_fail_closed(fact_policy, message) -> None:
    evidence, reviews = _p2_extract_candidate()
    candidate = evidence.candidates[0]
    source = candidate.source.model_copy(
        update={
            "structural_flags": candidate.source.structural_flags.model_copy(
                update={"effective_fact_policy": fact_policy}
            )
        }
    )
    candidate = candidate.model_copy(update={"source": source})
    evidence = evidence.model_copy(update={"candidates": [candidate]})

    with pytest.raises(IRValidationError, match=message):
        approve_claims(evidence, reviews, user_confirmations={"evidence.p2": True})
def test_evidence_revalidation_rejects_non_evidence_origin_domain(tmp_path) -> None:
    path, source_map, reference = _evidence_origin_fixture(tmp_path)
    company_origin = source_map.proposals[0].model_copy(update={"domain": ProposalDomain.COMPANY})
    source_map = source_map.model_copy(update={"proposals": [company_origin]})
    candidate = EvidenceCandidateIR(
        evidence_id="evidence.company-origin",
        proposal_id="proposal.origin",
        source=reference,
        proposed_claim=reference.exact_quote,
        confidence=1.0,
        reasoning="synthetic cross-domain origin",
    )

    with pytest.raises(IRValidationError, match="origin proposal domain .* not valid"):
        revalidate_evidence_input(
            NormalizedEvidenceInput(input_id="evidence-input", candidates=[candidate]),
            source_map,
            path.parent,
        )
def test_approval_rejects_input_unresolved_questions() -> None:
    evidence, reviews = _p2_extract_candidate()
    evidence = evidence.model_copy(update={"unresolved_questions": ["confirm scope"]})

    with pytest.raises(IRValidationError, match="normalized evidence input .* unresolved questions"):
        approve_claims(evidence, reviews, user_confirmations={"evidence.p2": True})


def test_approval_rejects_extractive_unresolved_questions() -> None:
    evidence, reviews = _p2_extract_candidate()
    candidate = evidence.candidates[0].model_copy(update={"unresolved_questions": ["confirm scope"]})
    evidence = evidence.model_copy(update={"candidates": [candidate]})

    with pytest.raises(IRValidationError, match="extractive approval cannot proceed with unresolved questions"):
        approve_claims(evidence, reviews, user_confirmations={"evidence.p2": True})
@pytest.mark.parametrize(
    "owner",
    [
        ProposalOwner.TEAM,
        ProposalOwner.ORGANIZATION,
        ProposalOwner.ROLE,
        ProposalOwner.COMPANY,
        ProposalOwner.UNKNOWN,
    ],
)
def test_approval_rejects_non_candidate_owners(owner) -> None:
    evidence, reviews = _p2_extract_candidate()
    candidate = evidence.candidates[0].model_copy(update={"owner": owner})
    evidence = evidence.model_copy(update={"candidates": [candidate]})

    with pytest.raises(IRValidationError, match="owner .* is not candidate"):
        approve_claims(evidence, reviews, user_confirmations={"evidence.p2": True})
