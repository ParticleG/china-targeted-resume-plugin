"""Strict, proof-carrying intermediate representations for Phase 1.

The models in this module deliberately contain metadata and exact evidence slices,
not source documents.  They are the boundary between semantic proposals and the
deterministic validation kernel.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


class CanonicalModel(BaseModel):
    """Base for all IR values; unknown keys are never silently discarded."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=False,
    )


class ClaimMode(StrEnum):
    EXTRACTIVE = "extractive"
    REVIEWED_SEMANTIC = "reviewed-semantic"


class ProposalDomain(StrEnum):
    ROLE = "role"
    COMPANY = "company"
    ROADMAP = "roadmap"
    EVIDENCE = "evidence"
    JOB_DESCRIPTION = "job-description"
    PERSONAL = "personal"


class ProposalOwner(StrEnum):
    CANDIDATE = "candidate"
    TEAM = "team"
    ORGANIZATION = "organization"
    ROLE = "role"
    COMPANY = "company"
    UNKNOWN = "unknown"


class FactPolicy(StrEnum):
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    F4 = "F4"
    F5 = "F5"
    F6 = "F6"


class DisclosurePolicy(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ReviewKind(StrEnum):
    EVIDENCE = "evidence"
    CONTRIBUTION_METRIC = "contribution_metric"
    PRIVACY = "privacy"
    REQUIREMENT = "requirement"


class ReviewOutcome(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DISAGREE = "disagree"
    NEEDS_CONFIRMATION = "needs_confirmation"


class ApprovalBasis(StrEnum):
    MECHANICAL = "mechanical"
    INDEPENDENT_REVIEW = "independent_review"
    USER_CONFIRMED = "user_confirmed"


class DisclosureDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    NEEDS_CONFIRMATION = "needs_confirmation"


class DisclosureAudience(StrEnum):
    RECRUITER = "recruiter"
    HIRING_TEAM = "hiring_team"
    PUBLIC = "public"
    INTERNAL = "internal"


StableId = Annotated[str, StringConstraints(min_length=1, max_length=240)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
SafeRelativePath = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
NonEmptyText = Annotated[str, StringConstraints(min_length=1)]


class SourceSpan(CanonicalModel):
    """An inclusive line range and a half-open UTF-8 byte range."""

    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> SourceSpan:
        if self.end_line < self.start_line:
            raise ValueError("source span end_line must be greater than or equal to start_line")
        if self.end_byte <= self.start_byte:
            raise ValueError("source span end_byte must be greater than start_byte")
        return self


class StructuralFlags(CanonicalModel):
    """Deterministic context captured for a source slice."""

    block_kind: NonEmptyText = "unknown"
    inside_fence: bool = False
    inside_blockquote: bool = False
    inside_html: bool = False
    is_example: bool = False
    is_template: bool = False
    is_quoted: bool = False
    negative_instruction: bool = False
    secret_path: bool = False
    secret_content: bool = False
    malformed: bool = False
    # Missing policy metadata must fail closed, matching policy.parse_policy_markers.
    effective_fact_policy: FactPolicy = FactPolicy.F5
    effective_disclosure_policy: DisclosurePolicy = DisclosurePolicy.P3

    @property
    def blocked(self) -> bool:
        return (
            self.inside_fence
            or self.inside_blockquote
            or self.inside_html
            or self.is_example
            or self.is_template
            or self.is_quoted
            or self.negative_instruction
            or self.secret_path
            or self.secret_content
            or self.malformed
            or self.effective_fact_policy == FactPolicy.F6
            or self.effective_disclosure_policy == DisclosurePolicy.P3
        )


class SourceReference(CanonicalModel):
    """A source identity plus one exact quote; never a source body."""

    path: SafeRelativePath
    source_hash: Sha256
    span: SourceSpan
    exact_quote: NonEmptyText
    structural_flags: StructuralFlags = Field(default_factory=StructuralFlags)
    heading_ancestry: list[NonEmptyText] = Field(default_factory=list)
    section_id: StableId | None = None
    block_id: StableId | None = None

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        from pathlib import PurePosixPath

        if "\x00" in value:
            raise ValueError("source path must not contain NUL")
        if "\\" in value:
            raise ValueError("source path must use POSIX separators")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or value != path.as_posix()
            or ".." in path.parts
            or "." in path.parts
        ):
            raise ValueError("source path must be a canonical relative path without empty, . or .. segments")
        return value


class HeadingMetadata(CanonicalModel):
    heading: NonEmptyText
    heading_ancestry: list[NonEmptyText] = Field(default_factory=list)
    duplicate_index: int = Field(default=0, ge=0)


class SourceDocumentIR(CanonicalModel):
    document_id: StableId
    path: SafeRelativePath
    source_hash: Sha256
    span: SourceSpan | None = None
    # A source document without explicit policy is treated as unconfirmed/private.
    document_fact_policy: FactPolicy = FactPolicy.F5
    document_disclosure_policy: DisclosurePolicy = DisclosurePolicy.P3
    validation_warnings: list[NonEmptyText] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        # Reuse SourceReference's path policy without exposing a mutable helper.
        return SourceReference.model_validate(
            {
                "path": value,
                "source_hash": "sha256:" + "0" * 64,
                "span": {"start_line": 1, "end_line": 1, "start_byte": 0, "end_byte": 1},
                "exact_quote": "_",
            }
        ).path


class SourceSectionIR(CanonicalModel):
    section_id: StableId
    document_id: StableId
    span: SourceSpan
    heading: NonEmptyText
    heading_ancestry: list[NonEmptyText] = Field(default_factory=list)
    duplicate_index: int = Field(default=0, ge=0)
    block_ids: list[StableId] = Field(default_factory=list)
    structural_flags: StructuralFlags = Field(default_factory=StructuralFlags)


class SourceBlockIR(CanonicalModel):
    block_id: StableId
    document_id: StableId
    section_id: StableId | None = None
    span: SourceSpan
    heading_ancestry: list[NonEmptyText] = Field(default_factory=list)
    structural_flags: StructuralFlags = Field(default_factory=StructuralFlags)


class SemanticProposal(CanonicalModel):
    """An agent proposal bound to one exact source slice."""

    proposal_id: StableId
    source: SourceReference
    domain: ProposalDomain
    owner: ProposalOwner
    proposed_claim: NonEmptyText
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: NonEmptyText
    claim_mode: ClaimMode = ClaimMode.EXTRACTIVE
    unresolved_questions: list[NonEmptyText] = Field(default_factory=list)
    contribution_qualifiers: list[NonEmptyText] = Field(default_factory=list)
    metric_qualifiers: list[NonEmptyText] = Field(default_factory=list)

    @property
    def path(self) -> str:
        return self.source.path

    @property
    def source_hash(self) -> str:
        return self.source.source_hash

    @property
    def span(self) -> SourceSpan:
        return self.source.span

    @property
    def exact_quote(self) -> str:
        return self.source.exact_quote


class SourceMapIR(CanonicalModel):
    """Persistent structural metadata and per-proposal exact quotes only."""

    schema_version: Literal[1] = 1
    documents: list[SourceDocumentIR] = Field(default_factory=list)
    sections: list[SourceSectionIR] = Field(default_factory=list)
    blocks: list[SourceBlockIR] = Field(default_factory=list)
    proposals: list[SemanticProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def _relationships(self) -> SourceMapIR:
        document_ids = [item.document_id for item in self.documents]
        document_paths = [item.path for item in self.documents]
        section_ids = [item.section_id for item in self.sections]
        block_ids = [item.block_id for item in self.blocks]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("source map contains duplicate document IDs")
        if len(document_paths) != len(set(document_paths)):
            raise ValueError("source map contains duplicate document paths")
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("source map contains duplicate section IDs")
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("source map contains duplicate block IDs")
        documents = set(document_ids)
        sections = {item.section_id: item for item in self.sections}
        blocks = {item.block_id: item for item in self.blocks}
        proposal_ids: set[str] = set()
        for section in self.sections:
            if section.document_id not in documents:
                raise ValueError(f"section {section.section_id!r} references unknown document {section.document_id!r}")
            for block_id in section.block_ids:
                block = blocks.get(block_id)
                if block is None or block.section_id != section.section_id:
                    raise ValueError(f"section {section.section_id!r} references inconsistent block {block_id!r}")
        for block in self.blocks:
            if block.document_id not in documents:
                raise ValueError(f"block {block.block_id!r} references unknown document {block.document_id!r}")
            if block.section_id is not None and block.section_id not in sections:
                raise ValueError(f"block {block.block_id!r} references unknown section {block.section_id!r}")
        for proposal in self.proposals:
            if proposal.proposal_id in proposal_ids:
                raise ValueError(f"duplicate proposal ID {proposal.proposal_id!r}")
            proposal_ids.add(proposal.proposal_id)
            document = next((item for item in self.documents if item.path == proposal.source.path), None)
            if document is None:
                raise ValueError(f"proposal {proposal.proposal_id!r} references unknown source path {proposal.source.path!r}")
            if document.source_hash != proposal.source.source_hash:
                raise ValueError(f"proposal {proposal.proposal_id!r} source hash does not match its document")
            if proposal.source.section_id is not None and proposal.source.section_id not in sections:
                raise ValueError(f"proposal {proposal.proposal_id!r} references unknown section {proposal.source.section_id!r}")
            if proposal.source.block_id is not None and proposal.source.block_id not in blocks:
                raise ValueError(f"proposal {proposal.proposal_id!r} references unknown block {proposal.source.block_id!r}")
        return self


class RoleRequirementIR(CanonicalModel):
    requirement_id: StableId
    text: NonEmptyText
    origin: Literal["explicit", "inferred"]
    source: SourceReference | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: NonEmptyText
    unresolved_questions: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _source_contract(self) -> RoleRequirementIR:
        if self.origin == "explicit" and self.source is None:
            raise ValueError("explicit role requirements require an exact source reference")
        return self


class NormalizedRoleInput(CanonicalModel):
    schema_version: Literal[1] = 1
    input_id: StableId
    domain: Literal[ProposalDomain.ROLE] = ProposalDomain.ROLE
    role_id: StableId | None = None
    role_title: NonEmptyText | None = None
    company_id: StableId | None = None
    company_name: NonEmptyText | None = None
    proposals: list[SemanticProposal] = Field(default_factory=list)
    requirements: list[RoleRequirementIR] = Field(default_factory=list)
    unresolved_questions: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _domain(self) -> NormalizedRoleInput:
        for proposal in self.proposals:
            if proposal.domain not in {ProposalDomain.ROLE, ProposalDomain.JOB_DESCRIPTION}:
                raise ValueError(f"role input proposal {proposal.proposal_id!r} has forbidden domain {proposal.domain.value!r}")
        return self


class EvidenceCandidateIR(CanonicalModel):
    evidence_id: StableId
    proposal_id: StableId | None = None
    source: SourceReference
    proposed_claim: NonEmptyText
    domain: Literal[ProposalDomain.EVIDENCE] = ProposalDomain.EVIDENCE
    owner: ProposalOwner = ProposalOwner.CANDIDATE
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: NonEmptyText
    claim_mode: ClaimMode = ClaimMode.EXTRACTIVE
    requirement_ids: list[StableId] = Field(default_factory=list)
    contribution_qualifiers: list[NonEmptyText] = Field(default_factory=list)
    metric_qualifiers: list[NonEmptyText] = Field(default_factory=list)
    unresolved_questions: list[NonEmptyText] = Field(default_factory=list)


class NormalizedEvidenceInput(CanonicalModel):
    schema_version: Literal[1] = 1
    input_id: StableId
    domain: Literal[ProposalDomain.EVIDENCE] = ProposalDomain.EVIDENCE
    candidates: list[EvidenceCandidateIR] = Field(default_factory=list)
    unresolved_questions: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> NormalizedEvidenceInput:
        ids = [item.evidence_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("normalized evidence input contains duplicate evidence IDs")
        return self


class ContributionQualifier(CanonicalModel):
    text: NonEmptyText
    scope: NonEmptyText | None = None
    actor: NonEmptyText | None = None


class MetricQualifier(CanonicalModel):
    text: NonEmptyText
    name: NonEmptyText | None = None
    value: NonEmptyText | None = None
    unit: NonEmptyText | None = None
    qualifier: NonEmptyText | None = None


class ReviewDecision(CanonicalModel):
    review_id: StableId
    evidence_id: StableId
    reviewer_id: StableId
    review_kind: ReviewKind
    outcome: ReviewOutcome
    reasoning: NonEmptyText
    approved_safe_claim: NonEmptyText | None = None
    contribution_qualifiers: list[ContributionQualifier] = Field(default_factory=list)
    metric_qualifiers: list[MetricQualifier] = Field(default_factory=list)
    disclosure_decision: DisclosureDecision | None = None
    disclosure_audience: DisclosureAudience | None = None
    disclosure_purpose: NonEmptyText | None = None
    user_confirmation_required: bool = False
    user_confirmed: bool = False
    questions: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def _review_fields(self) -> ReviewDecision:
        if self.review_kind == ReviewKind.PRIVACY:
            if self.disclosure_decision is None:
                raise ValueError("privacy review must include disclosure_decision")
            if self.disclosure_decision == DisclosureDecision.ALLOWED and (
                self.disclosure_audience is None or not self.disclosure_purpose
            ):
                raise ValueError("allowed privacy review must include disclosure_audience and disclosure_purpose")
        if self.user_confirmed and not self.user_confirmation_required:
            raise ValueError("user_confirmed cannot be set when user_confirmation_required is false")
        return self


class ReviewDecisionIR(CanonicalModel):
    schema_version: Literal[1] = 1
    decisions: list[ReviewDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> ReviewDecisionIR:
        ids = [item.review_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("review decisions contain duplicate review IDs")
        return self


class ApprovedClaimIR(CanonicalModel):
    """A claim whose final text is locked byte-for-byte to approved_safe_claim."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=False,
        frozen=True,
    )

    claim_id: StableId
    origin_evidence_ids: list[StableId] = Field(min_length=1)
    approved_safe_claim: NonEmptyText
    approval_basis: ApprovalBasis
    reviewer_decision_ids: list[StableId] = Field(default_factory=list)
    claim_mode: ClaimMode = ClaimMode.EXTRACTIVE
    contribution_qualifiers: list[ContributionQualifier] = Field(default_factory=list)
    metric_qualifiers: list[MetricQualifier] = Field(default_factory=list)
    disclosure_decision: DisclosureDecision = DisclosureDecision.ALLOWED
    disclosure_audience: DisclosureAudience | None = None
    disclosure_purpose: NonEmptyText | None = None

    @model_validator(mode="after")
    def _approval(self) -> ApprovedClaimIR:
        if self.approval_basis == ApprovalBasis.MECHANICAL:
            if self.claim_mode != ClaimMode.EXTRACTIVE:
                raise ValueError("mechanical approval is only valid for extractive claims")
            if self.reviewer_decision_ids:
                raise ValueError("mechanical approval must not claim reviewer decision IDs")
        elif self.approval_basis == ApprovalBasis.USER_CONFIRMED and self.claim_mode == ClaimMode.EXTRACTIVE:
            if not self.reviewer_decision_ids:
                raise ValueError("user-confirmed extractive approval requires the approving privacy review ID")
        else:
            if self.claim_mode != ClaimMode.REVIEWED_SEMANTIC:
                raise ValueError("independent approval requires reviewed-semantic claim mode")
            if not self.reviewer_decision_ids:
                raise ValueError("reviewed-semantic approval requires reviewer decision IDs")
        if self.disclosure_decision == DisclosureDecision.ALLOWED and (
            self.disclosure_audience is None or not self.disclosure_purpose
        ):
            raise ValueError("allowed disclosure requires audience and purpose")
        if self.disclosure_decision != DisclosureDecision.ALLOWED and self.disclosure_audience is not None:
            raise ValueError("non-allowed disclosure must not include a disclosure audience")
        return self


class ApprovedClaimsIR(CanonicalModel):
    schema_version: Literal[1] = 1
    claims: list[ApprovedClaimIR] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> ApprovedClaimsIR:
        ids = [item.claim_id for item in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("approved claims contain duplicate immutable claim IDs")
        return self


# Descriptive aliases used by callers that prefer the longer names.
SourceMapDocument = SourceDocumentIR
SourceMapSection = SourceSectionIR
SourceMapBlock = SourceBlockIR
SemanticEvidenceProposal = SemanticProposal
