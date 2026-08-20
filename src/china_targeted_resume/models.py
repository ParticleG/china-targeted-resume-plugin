"""Canonical, JSON-serializable models for the deterministic resume pipeline."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

StableId = Annotated[str, Field(min_length=1, max_length=240)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class TargetBasis(StrEnum):
    EXACT_CURRENT_JD = "exact-current-jd"
    EXACT_ROLE_PARTIAL_EVIDENCE = "exact-role-partial-evidence"
    COMPANY_ROLE_FAMILY = "company-role-family"
    INSUFFICIENT_TARGET = "insufficient-target"


class JdCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class OutputMode(StrEnum):
    TARGETED_APPLICATION = "targeted_application"
    PUBLIC_PORTFOLIO = "public_portfolio"
    MASTER_RESUME = "master_resume"


class ResumeVariant(StrEnum):
    RECRUITER_ONE_PAGE = "recruiter-one-page"
    TECHNICAL_TWO_PAGE = "technical-two-page"
    EXTENDED_THREE_PAGE = "extended-three-page"


class RoleMatchState(StrEnum):
    DIRECT_EVIDENCE = "已有直接证据"
    TRANSFERABLE_EXPERIENCE = "可迁移经验"
    KNOWLEDGE_WITHOUT_PRACTICE = "有知识无实践"
    CLEAR_GAP = "明确缺口"
    PENDING_CONFIRMATION = "待确认"


class ConstraintStatus(StrEnum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class FactState(StrEnum):
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    F4 = "F4"
    F5 = "F5"
    F6 = "F6"


class DisclosureLevel(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class RequirementOrigin(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    MIXED = "mixed"


class RequirementNecessity(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    RESPONSIBILITY = "responsibility"
    CONTEXT = "context"
    UNKNOWN = "unknown"


class GapSeverity(StrEnum):
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"


class ApplicationDecision(StrEnum):
    APPLY_NOW = "apply_now"
    APPLY_WITH_RISKS = "apply_with_risks"
    DEPRIORITIZE = "deprioritize"
    PENDING_INFORMATION = "pending_information"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceSpan(CanonicalModel):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_column: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def ordered(self) -> SourceSpan:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        if self.start_line == self.end_line and self.start_column and self.end_column and self.end_column < self.start_column:
            raise ValueError("end_column must not precede start_column")
        return self


class Freshness(CanonicalModel):
    dynamic: bool = False
    checked_at: datetime | None = None
    source_date: date | None = None
    expires_at: datetime | None = None
    stale: bool = False


class SourceRef(CanonicalModel):
    path: str | None = None
    url: HttpUrl | None = None
    title: str | None = None
    section: str | None = None
    source_hash: str | None = None
    source_type: str | None = None
    publisher: str | None = None
    published_at: date | None = None
    accessed_at: datetime | None = None

    @model_validator(mode="after")
    def located(self) -> SourceRef:
        if self.path is None and self.url is None:
            raise ValueError("a source requires path or url")
        return self


class SourceSection(CanonicalModel):
    document_id: StableId
    source_path: str
    source_hash: str
    title: str
    section: str
    section_anchor: str
    domain: str
    outgoing_internal_links: list[str] = Field(default_factory=list)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class SourceManifest(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    adapter: str
    root: Path
    generated_at: datetime
    documents: list[str] = Field(default_factory=list)
    sections: list[SourceSection] = Field(default_factory=list)


class CompanyRef(CanonicalModel):
    company_id: StableId
    display_name: str
    source_refs: list[str] = Field(default_factory=list)


class RoleRef(CanonicalModel):
    role_id: StableId
    title: str
    company_id: StableId | None = None
    requisition_id: str | None = None
    role_family: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class JdInput(CanonicalModel):
    text: str | None = None
    url: HttpUrl | None = None
    file: Path | None = None


class RoleRequest(CanonicalModel):
    company_ref: str | CompanyRef | None = None
    role_ref: str | RoleRef | None = None
    jd: JdInput = Field(default_factory=JdInput)


class RunRequest(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    source_root: Path
    source_adapter: str = "markdown-career-v1"
    company_ref: str | CompanyRef | None = None
    role_ref: str | RoleRef | None = None
    jd: JdInput = Field(default_factory=JdInput)
    application_constraints: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=dict)
    output_mode: OutputMode = OutputMode.TARGETED_APPLICATION
    language: str = "zh-CN"
    include_extended_profile: bool = False
    template: Literal["ats-simple", "human-readable"] = "ats-simple"
    persist_role_research: bool = False
    export_roadmap_handoff: bool = False
    refresh_external_sources: bool = False
    output_root: Path


class TargetContext(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    target_basis: TargetBasis
    company: str | None = None
    role: str | None = None
    company_ref: CompanyRef | None = None
    role_ref: RoleRef | None = None
    jd_completeness: JdCompleteness
    jd_source_date: date | None = None
    jd_checked_at: datetime | None = None
    explicit_requirement_coverage: Confidence | None = None
    evidence_coverage_summary: str | None = None
    coverage_calculation: dict[str, Any] | None = None
    staleness_risk: Literal["none", "low", "medium", "high", "unknown"] = "unknown"
    limitations: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def coverage_requires_current_jd(self) -> TargetContext:
        if self.target_basis != TargetBasis.EXACT_CURRENT_JD and self.explicit_requirement_coverage is not None:
            raise ValueError("coverage is only valid for an exact current JD")
        return self


class Requirement(CanonicalModel):
    requirement_id: StableId
    text: str = Field(min_length=1)
    verbatim_quote: str | None = None
    category: str
    necessity: RequirementNecessity
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    origin: RequirementOrigin
    source_ref: str | None = None
    source_span: SourceSpan | None = None
    inference_basis: str | None = None
    confidence: Confidence
    hard_gate: bool = False
    keywords: list[str] = Field(default_factory=list)
    business_context: str | None = None

    @model_validator(mode="after")
    def origin_contract(self) -> Requirement:
        if self.origin == RequirementOrigin.EXPLICIT:
            if not self.verbatim_quote or self.source_span is None or not self.source_ref:
                raise ValueError("explicit requirements need verbatim_quote, source_span, and source_ref")
            if self.inference_basis is not None:
                raise ValueError("explicit requirements cannot have inference_basis")
        elif self.origin == RequirementOrigin.INFERRED:
            if not self.inference_basis or not self.source_ref:
                raise ValueError("inferred requirements need inference_basis and source_ref")
            if self.verbatim_quote is not None or self.source_span is not None or self.hard_gate:
                raise ValueError("inferred requirements cannot claim quote/span or become hard gates")
        else:
            raise ValueError("requirements must be explicit or inferred, not mixed")
        return self


class Competency(CanonicalModel):
    competency_id: StableId
    requirement_ids: list[StableId] = Field(default_factory=list)
    dimension: str
    expected_depth: str
    system_scale: str | None = None
    responsibility_scope: str | None = None
    business_problem: str | None = None
    validation_signals: list[str] = Field(default_factory=list)
    origin: RequirementOrigin = RequirementOrigin.EXPLICIT
    inference_basis: str | None = None
    confidence: Confidence = 1.0
    source_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def inferred_content_has_basis(self) -> Competency:
        if self.origin != RequirementOrigin.EXPLICIT and not self.inference_basis:
            raise ValueError("inferred competency content needs inference_basis")
        return self


class ApplicationConstraint(CanonicalModel):
    constraint_id: StableId
    kind: str
    requirement_id: StableId | None = None
    hard_gate: bool = False
    status: ConstraintStatus = ConstraintStatus.UNKNOWN
    candidate_value: str | None = None
    required_value: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    checked_at: datetime | None = None
    impact: str | None = None


class EvidenceCandidate(CanonicalModel):
    candidate_id: StableId
    requirement_ids: list[StableId] = Field(default_factory=list)
    source: SourceRef
    source_span: SourceSpan | None = None
    body: str | None = Field(default=None, exclude=True, repr=False)
    snippet: str | None = Field(default=None, exclude=True, repr=False)
    proposed_claim: str
    fact_state: FactState
    disclosure: DisclosureLevel
    match_state: RoleMatchState
    confidence: Confidence = 1.0
    rejection_reasons: list[str] = Field(default_factory=list)


class EvidenceRecord(CanonicalModel):
    evidence_id: StableId
    requirement_ids: list[StableId] = Field(default_factory=list)
    source: SourceRef
    source_span: SourceSpan | None = None
    fact_state: FactState
    disclosure: DisclosureLevel
    match_state: RoleMatchState
    contribution_scope: str
    metric_precision: str | None = None
    safe_claim: str = Field(min_length=1)
    forbidden_expansions: list[str] = Field(default_factory=list)
    freshness: Freshness = Field(default_factory=Freshness)


class EvidenceMapping(CanonicalModel):
    requirement_id: StableId
    match_state: RoleMatchState
    evidence_ids: list[StableId] = Field(default_factory=list)
    selection_reason: str
    resume_priority: Confidence = 0.0
    interview_risks: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def direct_has_evidence(self) -> EvidenceMapping:
        if self.match_state == RoleMatchState.DIRECT_EVIDENCE and not self.evidence_ids:
            raise ValueError("direct evidence needs evidence_ids")
        return self


class Gap(CanonicalModel):
    gap_id: StableId
    requirement_id: StableId
    match_state: RoleMatchState
    severity: GapSeverity | None
    job_impact: str
    reason: str
    baseline_evidence_refs: list[str] = Field(default_factory=list)
    validation_direction: list[str] = Field(default_factory=list)
    roadmap_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def orthogonal_dimensions(self) -> Gap:
        if self.match_state == RoleMatchState.PENDING_CONFIRMATION:
            if self.severity is not None:
                raise ValueError("pending confirmation requires null severity")
        elif self.severity is None:
            raise ValueError("confirmed gaps require severity")
        if self.match_state == RoleMatchState.DIRECT_EVIDENCE:
            raise ValueError("direct evidence must not mechanically become a gap")
        return self


class NumericDiagnostic(CanonicalModel):
    score: float | None = None
    weights: dict[str, float]
    denominator: float = Field(gt=0)
    unknowns: list[str] = Field(default_factory=list)
    calculation: str
    heuristic: Literal[True] = True


class ApplicationRecommendation(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    decision: ApplicationDecision
    target_source_completeness: JdCompleteness
    hard_constraint_readiness: Literal["ready", "blocked", "pending", "not_applicable"]
    explicit_requirement_coverage: Confidence | None = None
    evidence_strength: Literal["strong", "medium", "weak", "unknown"]
    critical_gaps: list[StableId] = Field(default_factory=list)
    major_gaps: list[StableId] = Field(default_factory=list)
    pending_information: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    heuristic: bool = True
    numeric_diagnostic: NumericDiagnostic | None = None

    @model_validator(mode="after")
    def source_complete_for_coverage(self) -> ApplicationRecommendation:
        if self.target_source_completeness != JdCompleteness.COMPLETE and self.explicit_requirement_coverage is not None:
            raise ValueError("coverage must be null unless the target source is complete")
        return self


class RoadmapHandoffItem(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    gap_id: StableId
    requirement_id: StableId | None = None
    source_role_refs: list[str] = Field(default_factory=list)
    match_state: RoleMatchState
    severity: GapSeverity
    priority_reason: str
    baseline_evidence_refs: list[str] = Field(default_factory=list)
    target_capability: str
    prerequisite_gap_ids: list[StableId] = Field(default_factory=list)
    suggested_artifacts: list[str] = Field(default_factory=list)
    verification_signals: list[str] = Field(default_factory=list)
    target_owning_file: str

    @model_validator(mode="after")
    def confirmed_gap_only(self) -> RoadmapHandoffItem:
        if self.match_state in (RoleMatchState.PENDING_CONFIRMATION, RoleMatchState.DIRECT_EVIDENCE):
            raise ValueError("roadmap handoff requires a confirmed evidence gap")
        return self


class ProvenanceRecord(CanonicalModel):
    claim_id: StableId
    evidence_ids: list[StableId] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    fact_state: FactState
    disclosure: DisclosureLevel
    output_mode: OutputMode
    rendered_claim: str
    transformations: list[str] = Field(default_factory=list)


class PublicLink(CanonicalModel):
    label: str
    url: HttpUrl


class Contact(CanonicalModel):
    name: str
    phone: str | None = None
    email: str | None = None
    location: str | None = None
    links: list[PublicLink] = Field(default_factory=list)


class ResumeTarget(CanonicalModel):
    company: str | None = None
    role: str | None = None
    target_basis: TargetBasis


class ResumeBullet(CanonicalModel):
    text: str
    claim_ids: list[StableId] = Field(min_length=1)
    priority: Confidence = 0.5


class SkillGroup(CanonicalModel):
    group: str
    items: list[str] = Field(default_factory=list)


class Experience(CanonicalModel):
    organization: str
    role: str
    location: str | None = None
    start_date: str
    end_date: str
    context: str | None = None
    bullets: list[ResumeBullet] = Field(default_factory=list)


class Project(CanonicalModel):
    name: str
    role: str | None = None
    context: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[ResumeBullet] = Field(default_factory=list)


class Education(CanonicalModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    details: list[str] = Field(default_factory=list)


class Honor(CanonicalModel):
    name: str
    issuer: str | None = None
    date: str | None = None
    details: str | None = None


class RenderPolicy(CanonicalModel):
    minimum_pages: int = Field(default=1, ge=1, le=6)
    target_pages: int = Field(default=2, ge=1, le=6)
    template: Literal["ats-simple", "human-readable"] = "ats-simple"
    minimum_body_font_pt: float = Field(default=10.0, ge=10.0, le=16.0)
    minimum_margin_mm: float = Field(default=12.0, ge=12.0, le=30.0)

    @model_validator(mode="after")
    def page_range_is_ordered(self) -> RenderPolicy:
        if self.minimum_pages > self.target_pages:
            raise ValueError("minimum_pages must not exceed target_pages")
        return self


class ResumeDocument(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    variant: ResumeVariant = ResumeVariant.TECHNICAL_TWO_PAGE
    locale: str = "zh-CN"
    target: ResumeTarget
    contact: Contact
    headline: str
    summary: list[str] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    honors: list[Honor] = Field(default_factory=list)
    render_policy: RenderPolicy = Field(default_factory=RenderPolicy)
    provenance_refs: list[StableId] = Field(default_factory=list)


class ValidationReport(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    success: bool
    checks: list[str] | dict[str, bool] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pages: int | None = Field(default=None, ge=0, le=100)
    extracted_text: str | None = Field(default=None, exclude=True, repr=False)
    fonts: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self) -> ValidationReport:
        if self.success and self.errors:
            raise ValueError("successful reports cannot contain errors")
        return self


class RoleDossierIR(CanonicalModel):
    schema_version: int = Field(default=1, ge=1)
    target_context: TargetContext
    requirements: list[Requirement] = Field(default_factory=list)
    competencies: list[Competency] = Field(default_factory=list)
    application_constraints: list[ApplicationConstraint] = Field(default_factory=list)
    evidence_candidates: list[EvidenceCandidate] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    evidence_mappings: list[EvidenceMapping] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    application_recommendation: ApplicationRecommendation | None = None
    roadmap_handoff: list[RoadmapHandoffItem] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    source_manifest: SourceManifest | None = None
    limitations: list[str] = Field(default_factory=list)


# Descriptive aliases retained for callers that use explicit resume-section names.
ResumeExperience = Experience
ResumeProject = Project
ResumeEducation = Education
ResumeHonor = Honor
ContactLink = PublicLink
