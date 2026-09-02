"""Canonical, JSON-serializable models for the deterministic resume pipeline."""
from __future__ import annotations

from datetime import UTC, date, datetime
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

StableId = Annotated[str, Field(min_length=1, max_length=240)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

_EXPERIENCE_COMPOUND_MARKERS = (
    "/",
    "\\",
    ",",
    "，",
    "、",
    ";",
    "；",
    " + ",
    " and ",
    " or ",
    "与",
    "及",
    "和",
)
_ENGLISH_EXPERIENCE_DURATION = re.compile(
    r"(?<!\w)(?P<minimum>\d+(?:\.\d+)?)"
    r"(?:\s*[-–—]\s*(?P<maximum>\d+(?:\.\d+)?))?"
    r"\s*\+?\s*(?:years?|yrs?)\b"
    r"(?:\s*(?:or\s+more|and\s+above))?"
    r"\s+(?P<scope>[^.;\n]+)",
    re.I,
)
_CHINESE_EXPERIENCE_DURATION = re.compile(
    r"(?P<minimum>\d+(?:\.\d+)?)"
    r"(?:\s*[-–—至到]\s*(?P<maximum>\d+(?:\.\d+)?))?"
    r"\s*年(?:以上|及以上|起)?\s*(?P<scope>[^。；\n]+)",
)
_CANDIDATE_DURATION_CHECK = re.compile(
    r"(?:checked|verified|as\s+of|截至|核验(?:于)?)"
    r"\s*[:：]?\s*(?P<date>(?:19|20)\d{2}-\d{2}-\d{2})",
    re.I,
)
_REQUIREMENT_DURATION_LANGUAGE = re.compile(
    r"\b(?:at\s+least|minimum|required|must|no\s+less\s+than)\b|"
    r"(?:至少|不低于|最低|要求)",
    re.I,
)


def normalize_experience_scope(value: str) -> str:
    return "".join(
        character
        for character in value.casefold()
        if character.isalnum()
    )


def experience_scope_is_atomic(value: str) -> bool:
    padded = f" {value.casefold().strip()} "
    return bool(normalize_experience_scope(value)) and not any(
        marker in padded
        for marker in _EXPERIENCE_COMPOUND_MARKERS
    )


def parse_atomic_experience_duration(
    text: str,
) -> dict[str, float | str | None] | None:
    matches = [
        *list(_ENGLISH_EXPERIENCE_DURATION.finditer(text)),
        *list(_CHINESE_EXPERIENCE_DURATION.finditer(text)),
    ]
    if len(matches) != 1:
        return None
    match = matches[0]
    scope = match.group("scope").strip(" -*•·:：")
    scope = re.sub(
        r"^(?:of\s+|experience\s+(?:in|with)\s+)",
        "",
        scope,
        flags=re.I,
    )
    scope = re.sub(
        r"\s+experience$|经验$",
        "",
        scope,
        flags=re.I,
    ).strip()
    if not experience_scope_is_atomic(scope):
        return None
    maximum = match.group("maximum")
    return {
        "scope": scope,
        "unit": "years",
        "required_min_years": float(match.group("minimum")),
        "required_max_years": (
            float(maximum)
            if maximum is not None
            else None
        ),
    }

def parse_candidate_experience_duration_fact(
    text: str,
) -> dict[str, object] | None:
    if _REQUIREMENT_DURATION_LANGUAGE.search(text):
        return None
    duration = parse_atomic_experience_duration(text)
    checked = list(_CANDIDATE_DURATION_CHECK.finditer(text))
    if (
        duration is None
        or duration["required_max_years"] is not None
        or len(checked) != 1
    ):
        return None
    checked_at = datetime.fromisoformat(
        checked[0].group("date")
    ).replace(tzinfo=UTC)
    return {
        "scope": duration["scope"],
        "unit": "years",
        "years": duration["required_min_years"],
        "checked_at": checked_at,
    }


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
    complete: bool | None = None

    @model_validator(mode="after")
    def completeness_requires_input(self) -> JdInput:
        if self.complete is not None and not any((self.text, self.url, self.file)):
            raise ValueError("JD completeness requires JD text, file, or URL input")
        return self


class ExperienceDurationRequirement(CanonicalModel):
    scope: str = Field(min_length=1)
    unit: Literal["years"] = "years"
    required_min_years: float = Field(gt=0)
    required_max_years: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def threshold_is_atomic_and_ordered(
        self,
    ) -> ExperienceDurationRequirement:
        if not experience_scope_is_atomic(self.scope):
            raise ValueError(
                "experience duration requirement must name one atomic comparison object"
            )
        if (
            self.required_max_years is not None
            and self.required_max_years < self.required_min_years
        ):
            raise ValueError(
                "required_max_years must not be less than required_min_years"
            )
        return self


class ExperienceDurationBindingDiagnostic(CanonicalModel):
    candidate_scope: str = Field(min_length=1)
    required_scope: str = Field(min_length=1)
    unit: Literal["years"] = "years"
    candidate_years: float = Field(ge=0)
    required_min_years: float = Field(gt=0)
    required_max_years: float | None = Field(default=None, gt=0)
    evidence_refs: list[StableId] = Field(min_length=1)
    checked_at: datetime

    @model_validator(mode="after")
    def comparison_is_atomic_and_ordered(
        self,
    ) -> ExperienceDurationBindingDiagnostic:
        if not experience_scope_is_atomic(
            self.candidate_scope
        ) or not experience_scope_is_atomic(self.required_scope):
            raise ValueError(
                "experience duration scopes must each name one atomic comparison object"
            )
        if normalize_experience_scope(
            self.candidate_scope
        ) != normalize_experience_scope(self.required_scope):
            raise ValueError(
                "candidate_scope and required_scope must identify the same comparison object"
            )
        if (
            self.required_max_years is not None
            and self.required_max_years < self.required_min_years
        ):
            raise ValueError(
                "required_max_years must not be less than required_min_years"
            )
        return self


class ExperienceDurationNearMatchDiagnostic(
    ExperienceDurationBindingDiagnostic
):
    @model_validator(mode="after")
    def candidate_is_below_requirement(
        self,
    ) -> ExperienceDurationNearMatchDiagnostic:
        if self.candidate_years >= self.required_min_years:
            raise ValueError(
                "near-match diagnostic requires candidate_years below required_min_years"
            )
        return self


class ExperienceDurationDiagnosticBinding(CanonicalModel):
    requirement_id: StableId
    diagnostic: ExperienceDurationBindingDiagnostic


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
    experience_duration_diagnostics: list[ExperienceDurationDiagnosticBinding] = Field(default_factory=list)
    output_mode: OutputMode = OutputMode.TARGETED_APPLICATION
    language: str = "zh-CN"
    include_extended_profile: bool = False
    template: Literal["adaptive", "ats-simple", "human-readable"] = "adaptive"
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
    experience_duration: ExperienceDurationRequirement | None = None

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
        if self.experience_duration is not None:
            if self.origin is not RequirementOrigin.EXPLICIT:
                raise ValueError(
                    "experience duration threshold requires an explicit requirement"
                )
            parsed_duration = parse_atomic_experience_duration(
                self.verbatim_quote or ""
            )
            if parsed_duration is None:
                raise ValueError(
                    "experience duration threshold is not supported by one atomic verbatim duration"
                )
            expected_duration = (
                ExperienceDurationRequirement.model_validate(
                    parsed_duration
                )
            )
            if (
                expected_duration.model_dump(mode="python")
                != self.experience_duration.model_dump(mode="python")
            ):
                raise ValueError(
                    "experience duration threshold must exactly match the verbatim requirement"
                )
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

    @model_validator(mode="after")
    def requirements_remain_separate(self) -> ApplicationConstraint:
        normalized_kind = self.kind.casefold().replace("-", "_").strip()
        if normalized_kind in {
            "experience",
            "experience_duration",
            "years_of_experience",
            "skill",
            "skills",
            "technical_skill",
            "capability",
            "seniority",
            "工作年限",
            "经验年限",
            "技能",
            "能力",
        }:
            raise ValueError(
                "experience and skill thresholds belong to explicit requirements and evidence mappings"
            )
        return self


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


class CandidateExperienceDurationFact(CanonicalModel):
    scope: str = Field(min_length=1)
    unit: Literal["years"] = "years"
    years: float = Field(gt=0)
    checked_at: datetime

    @model_validator(mode="after")
    def scope_is_atomic(self) -> CandidateExperienceDurationFact:
        if not experience_scope_is_atomic(self.scope):
            raise ValueError(
                "candidate experience duration must name one atomic comparison object"
            )
        return self


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
    experience_duration_fact: CandidateExperienceDurationFact | None = None

    @model_validator(mode="after")
    def duration_fact_matches_owner(self) -> EvidenceRecord:
        fact = self.experience_duration_fact
        if fact is None:
            return self
        parsed = parse_candidate_experience_duration_fact(
            self.safe_claim
        )
        if parsed is None:
            raise ValueError(
                "candidate experience duration fact must be extractive from safe_claim"
            )
        expected = CandidateExperienceDurationFact.model_validate(parsed)
        if expected.model_dump(mode="python") != fact.model_dump(
            mode="python"
        ):
            raise ValueError(
                "candidate experience duration fact must exactly match safe_claim"
            )
        if (
            not self.source.path
            or not self.source.source_hash
            or self.source_span is None
        ):
            raise ValueError(
                "candidate experience duration fact requires owning path, hash, and source span"
            )
        if self.freshness.checked_at != fact.checked_at:
            raise ValueError(
                "candidate experience duration checked_at must match record freshness"
            )
        return self




class EvidenceMapping(CanonicalModel):
    requirement_id: StableId
    match_state: RoleMatchState
    evidence_ids: list[StableId] = Field(default_factory=list)
    selection_reason: str
    resume_priority: Confidence = 0.0
    interview_risks: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    experience_duration_diagnostic: ExperienceDurationNearMatchDiagnostic | None = None

    @model_validator(mode="after")
    def evidence_contract(self) -> EvidenceMapping:
        if self.match_state == RoleMatchState.DIRECT_EVIDENCE and not self.evidence_ids:
            raise ValueError("direct evidence needs evidence_ids")
        diagnostic = self.experience_duration_diagnostic
        if diagnostic is not None:
            if self.match_state not in {
                RoleMatchState.DIRECT_EVIDENCE,
                RoleMatchState.TRANSFERABLE_EXPERIENCE,
            }:
                raise ValueError(
                    "experience duration diagnostic requires direct or transferable practice evidence"
                )
            unknown_refs = set(diagnostic.evidence_refs) - set(
                self.evidence_ids
            )
            if unknown_refs:
                raise ValueError(
                    "experience duration diagnostic evidence_refs must be selected mapping evidence_ids"
                )
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
    near_match_requirements: list[StableId] = Field(default_factory=list)
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
