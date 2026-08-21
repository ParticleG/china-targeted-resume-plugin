import { createHash } from "node:crypto";
import { revalidateSourceReference } from "./source-identity.ts";
import { validateSchemaDocument } from "./schema.ts";

export type ClaimMode = "extractive" | "reviewed-semantic";
export type ApprovalBasis = "mechanical" | "independent_review" | "user_confirmed";
export type ReviewKind = "evidence" | "contribution_metric" | "privacy" | "requirement";
export type ReviewOutcome = "approve" | "reject" | "disagree" | "needs_confirmation";
export type DisclosureDecision = "allowed" | "denied" | "needs_confirmation";
export type DisclosureAudience = "recruiter" | "hiring_team" | "public" | "internal";
export type FactPolicy = "F1" | "F2" | "F3" | "F4" | "F5" | "F6";
export type DisclosurePolicy = "P0" | "P1" | "P2" | "P3";

export interface SourceSpan {
  readonly start_line: number;
  readonly end_line: number;
  readonly start_byte: number;
  readonly end_byte: number;
}

export interface StructuralFlags {
  readonly block_kind: string;
  readonly inside_fence: boolean;
  readonly inside_blockquote: boolean;
  readonly inside_html: boolean;
  readonly is_example: boolean;
  readonly is_template: boolean;
  readonly is_quoted: boolean;
  readonly negative_instruction: boolean;
  readonly secret_path: boolean;
  readonly secret_content: boolean;
  readonly malformed: boolean;
  readonly effective_fact_policy: FactPolicy;
  readonly effective_disclosure_policy: DisclosurePolicy;
}

export interface SourceReference {
  readonly path: string;
  readonly source_hash: `sha256:${string}`;
  readonly span: SourceSpan;
  readonly exact_quote: string;
  readonly structural_flags: StructuralFlags;
  readonly heading_ancestry: readonly string[];
  readonly section_id: string | null;
  readonly block_id: string | null;
}

export interface EvidenceCandidateIR {
  readonly evidence_id: string;
  readonly proposal_id: string | null;
  readonly source: SourceReference;
  readonly proposed_claim: string;
  readonly domain: "evidence";
  readonly owner: "candidate" | "team" | "organization" | "role" | "company" | "unknown";
  readonly confidence: number;
  readonly reasoning: string;
  readonly claim_mode: ClaimMode;
  readonly requirement_ids: readonly string[];
  readonly contribution_qualifiers: readonly string[];
  readonly metric_qualifiers: readonly string[];
  readonly unresolved_questions: readonly string[];
}

export interface NormalizedEvidenceInput {
  readonly schema_version: 1;
  readonly input_id: string;
  readonly domain: "evidence";
  readonly candidates: readonly EvidenceCandidateIR[];
  readonly unresolved_questions: readonly string[];
}

export interface ContributionQualifier {
  readonly text: string;
  readonly scope: string | null;
  readonly actor: string | null;
}

export interface MetricQualifier {
  readonly text: string;
  readonly name: string | null;
  readonly value: string | null;
  readonly unit: string | null;
  readonly qualifier: string | null;
}

export interface ReviewDecision {
  readonly review_id: string;
  readonly evidence_id: string;
  readonly reviewer_id: string;
  readonly review_kind: ReviewKind;
  readonly outcome: ReviewOutcome;
  readonly reasoning: string;
  readonly approved_safe_claim: string | null;
  readonly contribution_qualifiers: readonly ContributionQualifier[];
  readonly metric_qualifiers: readonly MetricQualifier[];
  readonly disclosure_decision: DisclosureDecision | null;
  readonly disclosure_audience: DisclosureAudience | null;
  readonly disclosure_purpose: string | null;
  readonly user_confirmation_required: boolean;
  readonly user_confirmed: boolean;
  readonly questions: readonly string[];
}

export interface ReviewDecisionIR {
  readonly schema_version: 1;
  readonly decisions: readonly ReviewDecision[];
}

export interface ApprovedClaimIR {
  readonly claim_id: string;
  readonly origin_evidence_ids: readonly string[];
  readonly approved_safe_claim: string;
  readonly approval_basis: ApprovalBasis;
  readonly reviewer_decision_ids: readonly string[];
  readonly claim_mode: ClaimMode;
  readonly contribution_qualifiers: readonly ContributionQualifier[];
  readonly metric_qualifiers: readonly MetricQualifier[];
  readonly disclosure_decision: DisclosureDecision;
  readonly disclosure_audience: DisclosureAudience | null;
  readonly disclosure_purpose: string | null;
}

export interface ApprovedClaimsIR {
  readonly schema_version: 1;
  readonly claims: readonly ApprovedClaimIR[];
}
export type ApprovalOutputMode = "targeted_application" | "public_portfolio" | "master_resume";
export type ConfirmationReason =
  | "p2_disclosure"
  | "candidate_unresolved_questions"
  | "reviewer_confirmation";

export interface ConfirmationRequest {
  readonly schema_version: 1;
  readonly run_id: string;
  readonly evidence_id: string;
  readonly claim_digest: `sha256:${string}`;
  readonly disclosure_audience: "recruiter" | "hiring_team";
  readonly disclosure_purpose: string;
  readonly output_mode: "targeted_application";
  readonly reason_codes: readonly ConfirmationReason[];
}

export interface ConfirmationReceipt extends ConfirmationRequest {
  readonly confirmed: true;
  readonly confirmed_at: string;
  readonly confirmed_by: "interactive_user";
  readonly nonce: string;
}

export interface ApproveClaimsOptions {
  readonly approvedSafeClaims?: Readonly<Record<string, string>>;
  readonly confirmationReceipts?: readonly ConfirmationReceipt[];
  readonly runId?: string;
  readonly outputMode?: ApprovalOutputMode;
}

export interface ApprovalLock {
  readonly schema_version: 1;
  readonly backend: "typescript";
  readonly run_id: string;
  readonly evidence_input_id: string;
  readonly evidence_ids: readonly string[];
  readonly review_decision_ids: readonly string[];
  readonly claim_ids: readonly string[];
  readonly digest: `sha256:${string}`;
}
export interface ApproveAndLockResult {
  readonly backend: "typescript";
  readonly approved_claims: ApprovedClaimsIR;
  readonly approval_lock: ApprovalLock;
}

export class KernelValidationError extends Error {
  readonly code: string;
  readonly issues: readonly string[];

  constructor(
    message: string,
    issues: readonly string[] = [message],
    code = "KERNEL_VALIDATION_FAILED",
  ) {
    const normalized = issues.length > 0 ? [...issues] : [message];
    super(normalized.length === 1 ? message : normalized.join("; "));
    this.name = "KernelValidationError";
    this.code = code;
    this.issues = Object.freeze(normalized);
  }
}

const LIST_MARKER = /^(?:[-+*]|\p{Decimal_Number}+[.)])(?:[ \t]+|$)/u;
const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/u;
const REQUIRED_REVIEW_KINDS = ["evidence", "contribution_metric", "privacy"] as const;
const STRUCTURAL_BLOCK_FLAGS = [
  "inside_fence",
  "inside_blockquote",
  "inside_html",
  "is_example",
  "is_template",
  "is_quoted",
  "negative_instruction",
  "secret_path",
  "secret_content",
  "malformed",
] as const;
function pythonQuoted(value: string): string {
  const escaped = value
    .replaceAll("\\", "\\\\")
    .replaceAll("'", "\\'")
    .replaceAll("\n", "\\n")
    .replaceAll("\r", "\\r")
    .replaceAll("\t", "\\t");
  return `'${escaped}'`;
}

function pythonStringList(values: readonly string[]): string {
  return `[${values.map(pythonQuoted).join(", ")}]`;
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new KernelValidationError(`${label} must be a JSON object`);
  return value;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new KernelValidationError(`${label} must be an array`);
  return value;
}

function stringArray(value: unknown, label: string): readonly string[] {
  const values = array(value, label);
  if (!values.every((item) => typeof item === "string" && item.length > 0)) {
    throw new KernelValidationError(`${label} must contain non-empty strings`);
  }
  return Object.freeze([...values] as string[]);
}

function optionalString(value: unknown, label: string): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || value.length === 0) {
    throw new KernelValidationError(`${label} must be null or a non-empty string`);
  }
  return value;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new KernelValidationError(`${label} must be a non-empty string`);
  }
  return value;
}

function booleanDefault(value: unknown, fallback = false): boolean {
  if (value === undefined) return fallback;
  if (typeof value !== "boolean") throw new KernelValidationError("boolean field has a non-boolean value");
  return value;
}

function assertSafeRelativePath(value: string): void {
  if (value.includes("\0") || value.includes("\\") || value.startsWith("/")) {
    throw new KernelValidationError("source path must be a normalized relative path without . or .. segments");
  }
  const parts = value.split("/");
  if (parts.length === 0 || parts.some((part) => part === "" || part === "." || part === "..")) {
    throw new KernelValidationError("source path must be a normalized relative path without . or .. segments");
  }
}

function normalizeContributionQualifier(value: unknown, label: string): ContributionQualifier {
  const item = record(value, label);
  return Object.freeze({
    text: requiredString(item.text, `${label}.text`),
    scope: optionalString(item.scope, `${label}.scope`),
    actor: optionalString(item.actor, `${label}.actor`),
  });
}

function normalizeMetricQualifier(value: unknown, label: string): MetricQualifier {
  const item = record(value, label);
  return Object.freeze({
    text: requiredString(item.text, `${label}.text`),
    name: optionalString(item.name, `${label}.name`),
    value: optionalString(item.value, `${label}.value`),
    unit: optionalString(item.unit, `${label}.unit`),
    qualifier: optionalString(item.qualifier, `${label}.qualifier`),
  });
}

function normalizeSpan(value: unknown, label: string): SourceSpan {
  const item = record(value, label);
  const startLine = item.start_line;
  const endLine = item.end_line;
  const startByte = item.start_byte;
  const endByte = item.end_byte;
  if (![startLine, endLine, startByte, endByte].every(Number.isInteger)) {
    throw new KernelValidationError(`${label} fields must be integers`);
  }
  const span = {
    start_line: startLine as number,
    end_line: endLine as number,
    start_byte: startByte as number,
    end_byte: endByte as number,
  };
  if (span.end_line < span.start_line) {
    throw new KernelValidationError("source span end_line must be greater than or equal to start_line");
  }
  if (span.end_byte <= span.start_byte) {
    throw new KernelValidationError("source span end_byte must be greater than start_byte");
  }
  return Object.freeze(span);
}

function normalizeStructuralFlags(value: unknown): StructuralFlags {
  const item = value === undefined ? {} : record(value, "structural_flags");
  const effectiveFact = (item.effective_fact_policy ?? "F5") as FactPolicy;
  const effectiveDisclosure = (item.effective_disclosure_policy ?? "P3") as DisclosurePolicy;
  return Object.freeze({
    block_kind: item.block_kind === undefined ? "unknown" : requiredString(item.block_kind, "structural_flags.block_kind"),
    inside_fence: booleanDefault(item.inside_fence),
    inside_blockquote: booleanDefault(item.inside_blockquote),
    inside_html: booleanDefault(item.inside_html),
    is_example: booleanDefault(item.is_example),
    is_template: booleanDefault(item.is_template),
    is_quoted: booleanDefault(item.is_quoted),
    negative_instruction: booleanDefault(item.negative_instruction),
    secret_path: booleanDefault(item.secret_path),
    secret_content: booleanDefault(item.secret_content),
    malformed: booleanDefault(item.malformed),
    effective_fact_policy: effectiveFact,
    effective_disclosure_policy: effectiveDisclosure,
  });
}

function normalizeSourceReference(value: unknown, label: string): SourceReference {
  const item = record(value, label);
  const path = requiredString(item.path, `${label}.path`);
  assertSafeRelativePath(path);
  const sourceHash = requiredString(item.source_hash, `${label}.source_hash`);
  if (!SHA256_PATTERN.test(sourceHash)) throw new KernelValidationError(`${label}.source_hash must be sha256:<64 lowercase hex>`);
  return Object.freeze({
    path,
    source_hash: sourceHash as `sha256:${string}`,
    span: normalizeSpan(item.span, `${label}.span`),
    exact_quote: requiredString(item.exact_quote, `${label}.exact_quote`),
    structural_flags: normalizeStructuralFlags(item.structural_flags),
    heading_ancestry: item.heading_ancestry === undefined
      ? Object.freeze([])
      : stringArray(item.heading_ancestry, `${label}.heading_ancestry`),
    section_id: optionalString(item.section_id, `${label}.section_id`),
    block_id: optionalString(item.block_id, `${label}.block_id`),
  });
}

function normalizeEvidenceCandidate(value: unknown, index: number): EvidenceCandidateIR {
  const label = `candidates[${index}]`;
  const item = record(value, label);
  return Object.freeze({
    evidence_id: requiredString(item.evidence_id, `${label}.evidence_id`),
    proposal_id: optionalString(item.proposal_id, `${label}.proposal_id`),
    source: normalizeSourceReference(item.source, `${label}.source`),
    proposed_claim: requiredString(item.proposed_claim, `${label}.proposed_claim`),
    domain: "evidence",
    owner: (item.owner ?? "candidate") as EvidenceCandidateIR["owner"],
    confidence: item.confidence as number,
    reasoning: requiredString(item.reasoning, `${label}.reasoning`),
    claim_mode: (item.claim_mode ?? "extractive") as ClaimMode,
    requirement_ids: item.requirement_ids === undefined ? Object.freeze([]) : stringArray(item.requirement_ids, `${label}.requirement_ids`),
    contribution_qualifiers: item.contribution_qualifiers === undefined
      ? Object.freeze([])
      : stringArray(item.contribution_qualifiers, `${label}.contribution_qualifiers`),
    metric_qualifiers: item.metric_qualifiers === undefined
      ? Object.freeze([])
      : stringArray(item.metric_qualifiers, `${label}.metric_qualifiers`),
    unresolved_questions: item.unresolved_questions === undefined
      ? Object.freeze([])
      : stringArray(item.unresolved_questions, `${label}.unresolved_questions`),
  });
}

export function normalizeEvidenceInput(value: unknown): NormalizedEvidenceInput {
  const validated = validateSchemaDocument(value, "normalized-evidence-input") as unknown as Record<string, unknown>;
  const candidates = validated.candidates === undefined ? [] : array(validated.candidates, "candidates");
  const normalizedCandidates = candidates.map(normalizeEvidenceCandidate);
  const ids = normalizedCandidates.map((candidate) => candidate.evidence_id);
  if (new Set(ids).size !== ids.length) {
    throw new KernelValidationError("normalized evidence input contains duplicate evidence IDs");
  }
  return Object.freeze({
    schema_version: 1,
    input_id: requiredString(validated.input_id, "input_id"),
    domain: "evidence",
    candidates: Object.freeze(normalizedCandidates),
    unresolved_questions: validated.unresolved_questions === undefined
      ? Object.freeze([])
      : stringArray(validated.unresolved_questions, "unresolved_questions"),
  });
}

function normalizeReviewDecision(value: unknown, index: number): ReviewDecision {
  const label = `decisions[${index}]`;
  const item = record(value, label);
  const contribution = item.contribution_qualifiers === undefined
    ? []
    : array(item.contribution_qualifiers, `${label}.contribution_qualifiers`);
  const metrics = item.metric_qualifiers === undefined
    ? []
    : array(item.metric_qualifiers, `${label}.metric_qualifiers`);
  const decision: ReviewDecision = Object.freeze({
    review_id: requiredString(item.review_id, `${label}.review_id`),
    evidence_id: requiredString(item.evidence_id, `${label}.evidence_id`),
    reviewer_id: requiredString(item.reviewer_id, `${label}.reviewer_id`),
    review_kind: item.review_kind as ReviewKind,
    outcome: item.outcome as ReviewOutcome,
    reasoning: requiredString(item.reasoning, `${label}.reasoning`),
    approved_safe_claim: optionalString(item.approved_safe_claim, `${label}.approved_safe_claim`),
    contribution_qualifiers: Object.freeze(contribution.map((entry, qualifierIndex) => (
      normalizeContributionQualifier(entry, `${label}.contribution_qualifiers[${qualifierIndex}]`)
    ))),
    metric_qualifiers: Object.freeze(metrics.map((entry, qualifierIndex) => (
      normalizeMetricQualifier(entry, `${label}.metric_qualifiers[${qualifierIndex}]`)
    ))),
    disclosure_decision: item.disclosure_decision === undefined ? null : item.disclosure_decision as DisclosureDecision | null,
    disclosure_audience: item.disclosure_audience === undefined ? null : item.disclosure_audience as DisclosureAudience | null,
    disclosure_purpose: optionalString(item.disclosure_purpose, `${label}.disclosure_purpose`),
    user_confirmation_required: booleanDefault(item.user_confirmation_required),
    user_confirmed: booleanDefault(item.user_confirmed),
    questions: item.questions === undefined ? Object.freeze([]) : stringArray(item.questions, `${label}.questions`),
  });
  if (decision.review_kind === "privacy") {
    if (decision.disclosure_decision === null) {
      throw new KernelValidationError("privacy review must include disclosure_decision");
    }
    if (decision.disclosure_decision === "allowed" && (
      decision.disclosure_audience === null || decision.disclosure_purpose === null
    )) {
      throw new KernelValidationError("allowed privacy review must include disclosure_audience and disclosure_purpose");
    }
  }
  if (decision.user_confirmed && !decision.user_confirmation_required) {
    throw new KernelValidationError("user_confirmed cannot be set when user_confirmation_required is false");
  }
  return decision;
}

export function normalizeReviewDecisions(value: unknown): ReviewDecisionIR {
  const candidate = Array.isArray(value) ? { schema_version: 1, decisions: value } : value;
  const validated = validateSchemaDocument(candidate, "review-decision") as unknown as Record<string, unknown>;
  const decisions = validated.decisions === undefined ? [] : array(validated.decisions, "decisions");
  const normalized = decisions.map(normalizeReviewDecision);
  const ids = normalized.map((decision) => decision.review_id);
  if (new Set(ids).size !== ids.length) {
    throw new KernelValidationError("review decisions contain duplicate review IDs");
  }
  return Object.freeze({ schema_version: 1, decisions: Object.freeze(normalized) });
}

function normalizeApprovedClaim(value: unknown, index: number): ApprovedClaimIR {
  const label = `claims[${index}]`;
  const item = record(value, label);
  const contributions = item.contribution_qualifiers === undefined
    ? []
    : array(item.contribution_qualifiers, `${label}.contribution_qualifiers`);
  const metrics = item.metric_qualifiers === undefined
    ? []
    : array(item.metric_qualifiers, `${label}.metric_qualifiers`);
  const claim: ApprovedClaimIR = Object.freeze({
    claim_id: requiredString(item.claim_id, `${label}.claim_id`),
    origin_evidence_ids: stringArray(item.origin_evidence_ids, `${label}.origin_evidence_ids`),
    approved_safe_claim: requiredString(item.approved_safe_claim, `${label}.approved_safe_claim`),
    approval_basis: item.approval_basis as ApprovalBasis,
    reviewer_decision_ids: item.reviewer_decision_ids === undefined
      ? Object.freeze([])
      : stringArray(item.reviewer_decision_ids, `${label}.reviewer_decision_ids`),
    claim_mode: (item.claim_mode ?? "extractive") as ClaimMode,
    contribution_qualifiers: Object.freeze(contributions.map((entry, qualifierIndex) => (
      normalizeContributionQualifier(entry, `${label}.contribution_qualifiers[${qualifierIndex}]`)
    ))),
    metric_qualifiers: Object.freeze(metrics.map((entry, qualifierIndex) => (
      normalizeMetricQualifier(entry, `${label}.metric_qualifiers[${qualifierIndex}]`)
    ))),
    disclosure_decision: (item.disclosure_decision ?? "allowed") as DisclosureDecision,
    disclosure_audience: item.disclosure_audience === undefined ? null : item.disclosure_audience as DisclosureAudience | null,
    disclosure_purpose: optionalString(item.disclosure_purpose, `${label}.disclosure_purpose`),
  });
  if (claim.approval_basis === "mechanical") {
    if (claim.claim_mode !== "extractive") {
      throw new KernelValidationError("mechanical approval is only valid for extractive claims");
    }
    if (claim.reviewer_decision_ids.length > 0) {
      throw new KernelValidationError("mechanical approval must not claim reviewer decision IDs");
    }
  } else if (claim.approval_basis === "independent_review") {
    if (claim.claim_mode !== "reviewed-semantic") {
      throw new KernelValidationError("independent approval requires reviewed-semantic claim mode");
    }
    if (claim.reviewer_decision_ids.length === 0) {
      throw new KernelValidationError("reviewed-semantic approval requires reviewer decision IDs");
    }
  } else if (claim.reviewer_decision_ids.length === 0) {
    throw new KernelValidationError("user-confirmed approval requires reviewer decision IDs");
  }
  if (claim.disclosure_decision === "allowed" && (
    claim.disclosure_audience === null || claim.disclosure_purpose === null
  )) {
    throw new KernelValidationError("allowed disclosure requires audience and purpose");
  }
  if (claim.disclosure_decision !== "allowed" && claim.disclosure_audience !== null) {
    throw new KernelValidationError("non-allowed disclosure must not include a disclosure audience");
  }
  return claim;
}

export function normalizeApprovedClaims(value: unknown): ApprovedClaimsIR {
  const validated = validateSchemaDocument(value, "approved-claims") as unknown as Record<string, unknown>;
  const claims = validated.claims === undefined ? [] : array(validated.claims, "claims");
  const normalized = claims.map(normalizeApprovedClaim);
  const ids = normalized.map((claim) => claim.claim_id);
  if (new Set(ids).size !== ids.length) {
    throw new KernelValidationError("approved claims contain duplicate immutable claim IDs");
  }
  return Object.freeze({ schema_version: 1, claims: Object.freeze(normalized) });
}

function collapseMechanicalWhitespace(value: string): string {
  return value.trim().replace(/\s+/gu, " ");
}

function removeListMarkers(value: string): string {
  return value.split(/\r\n|[\n\v\f\r\x1c-\x1e\x85\u2028\u2029]/u).map((line) => {
    const stripped = line.trim();
    const marker = LIST_MARKER.exec(stripped);
    return marker === null ? stripped : stripped.slice(marker[0].length);
  }).join(" ");
}

export function normalizeExtractiveClaim(exactQuote: unknown, proposedClaim: unknown): string {
  if (typeof exactQuote !== "string" || typeof proposedClaim !== "string") {
    throw new KernelValidationError("extractive normalization requires string exact_quote and proposed_claim");
  }
  if (exactQuote.trim().length === 0 || proposedClaim.trim().length === 0) {
    throw new KernelValidationError("extractive normalization requires non-empty text");
  }
  if (exactQuote === proposedClaim) return proposedClaim;
  if (collapseMechanicalWhitespace(exactQuote) === collapseMechanicalWhitespace(proposedClaim)) {
    return proposedClaim.trim();
  }
  if (collapseMechanicalWhitespace(removeListMarkers(exactQuote)) === collapseMechanicalWhitespace(removeListMarkers(proposedClaim))) {
    return proposedClaim.trim();
  }
  throw new KernelValidationError(
    "extractive claim is not an exact quote or a supported mechanical whitespace/list-marker normalization",
  );
}

function structuralPolicyBlocked(flags: StructuralFlags): boolean {
  return STRUCTURAL_BLOCK_FLAGS.some((name) => flags[name])
    || flags.effective_fact_policy === "F6"
    || flags.effective_disclosure_policy === "P3";
}

function normalizeStringMap(value: unknown, label: string): Readonly<Record<string, string>> {
  if (value === undefined || value === null) return Object.freeze({});
  const item = record(value, label);
  const result: Record<string, string> = {};
  for (const [key, entry] of Object.entries(item)) {
    if (typeof entry !== "string") throw new KernelValidationError(`${label}.${key} must be a string`);
    result[key] = entry;
  }
  return Object.freeze(result);
}

function claimTextSha256(text: string): `sha256:${string}` {
  return `sha256:${createHash("sha256").update(text, "utf8").digest("hex")}`;
}

function normalizeConfirmationReceipt(value: unknown, index: number): ConfirmationReceipt {
  const label = `confirmation_receipts[${index}]`;
  const item = validateSchemaDocument(value, "confirmation") as unknown as Record<string, unknown>;
  const audience = item.disclosure_audience;
  if (audience !== "recruiter" && audience !== "hiring_team") {
    throw new KernelValidationError(`${label}.disclosure_audience must be recruiter or hiring_team`);
  }
  if (item.output_mode !== "targeted_application") {
    throw new KernelValidationError(`${label}.output_mode must be targeted_application`);
  }
  if (item.confirmed_by !== "interactive_user") {
    throw new KernelValidationError(`${label}.confirmed_by must be interactive_user`);
  }
  if (item.confirmed !== true) throw new KernelValidationError(`${label}.confirmed must be true`);
  const claimDigest = requiredString(item.claim_digest, `${label}.claim_digest`);
  if (!SHA256_PATTERN.test(claimDigest)) throw new KernelValidationError(`${label}.claim_digest is invalid`);
  const reasonCodes = stringArray(item.reason_codes, `${label}.reason_codes`);
  if (reasonCodes.some((reason) => (
    reason !== "p2_disclosure"
    && reason !== "candidate_unresolved_questions"
    && reason !== "reviewer_confirmation"
  ))) {
    throw new KernelValidationError(`${label}.reason_codes contains an unknown reason`);
  }
  const confirmedAt = requiredString(item.confirmed_at, `${label}.confirmed_at`);
  if (Number.isNaN(Date.parse(confirmedAt))) throw new KernelValidationError(`${label}.confirmed_at must be an ISO timestamp`);
  return Object.freeze({
    schema_version: 1,
    run_id: requiredString(item.run_id, `${label}.run_id`),
    evidence_id: requiredString(item.evidence_id, `${label}.evidence_id`),
    claim_digest: claimDigest as `sha256:${string}`,
    disclosure_audience: audience,
    disclosure_purpose: requiredString(item.disclosure_purpose, `${label}.disclosure_purpose`),
    output_mode: "targeted_application",
    reason_codes: reasonCodes as readonly ConfirmationReason[],
    confirmed: true,
    confirmed_by: "interactive_user",
    confirmed_at: confirmedAt,
    nonce: requiredString(item.nonce, `${label}.nonce`),
  });
}

function normalizeConfirmationReceipts(value: unknown): readonly ConfirmationReceipt[] {
  if (value === undefined) return Object.freeze([]);
  const values = array(value, "confirmation_receipts");
  const receipts = values.map(normalizeConfirmationReceipt);
  const evidenceIds = receipts.map((receipt) => receipt.evidence_id);
  if (new Set(evidenceIds).size !== evidenceIds.length) {
    throw new KernelValidationError("confirmation receipts contain duplicate evidence IDs");
  }
  return Object.freeze(receipts);
}

function claimTextForCandidate(
  candidate: EvidenceCandidateIR,
  approvedSafeClaims: Readonly<Record<string, string>>,
): string {
  if (candidate.claim_mode === "extractive") {
    return normalizeExtractiveClaim(
      candidate.source.exact_quote,
      approvedSafeClaims[candidate.evidence_id] ?? candidate.proposed_claim,
    );
  }
  const claimText = approvedSafeClaims[candidate.evidence_id] ?? "";
  if (claimText.length === 0) {
    throw new KernelValidationError(
      `evidence ${pythonQuoted(candidate.evidence_id)}: reviewed-semantic approval requires exact approved_safe_claim`,
    );
  }
  return claimText;
}

function approvalPreflight(
  evidence: NormalizedEvidenceInput,
  reviews: ReviewDecisionIR,
): ReadonlyMap<string, readonly ReviewDecision[]> {
  if (evidence.unresolved_questions.length > 0) {
    const message = `normalized evidence input '${evidence.input_id}' has unresolved questions; approval fails closed until revalidated`;
    throw new KernelValidationError(message, [message], "EVIDENCE_INPUT_UNRESOLVED_QUESTIONS");
  }
  const byEvidence = new Map<string, ReviewDecision[]>();
  for (const review of reviews.decisions) {
    const existing = byEvidence.get(review.evidence_id) ?? [];
    existing.push(review);
    byEvidence.set(review.evidence_id, existing);
  }
  const knownIds = new Set(evidence.candidates.map((candidate) => candidate.evidence_id));
  const unknown = [...byEvidence.keys()].filter((id) => !knownIds.has(id)).sort();
  if (unknown.length > 0) {
    throw new KernelValidationError(`review decisions reference unknown evidence IDs: ${pythonStringList(unknown)}`);
  }
  for (const candidate of evidence.candidates) {
    const candidateReviews = byEvidence.get(candidate.evidence_id) ?? [];
    if (candidate.owner !== "candidate") {
      const message = `evidence '${candidate.evidence_id}': owner ${candidate.owner} is not candidate; ownership must be resolved in reviewed candidate IR`;
      throw new KernelValidationError(message, [message], "EVIDENCE_OWNER_NOT_CANDIDATE");
    }
    if (candidateReviews.some((review) => review.review_kind === "requirement")) {
      const message = `evidence '${candidate.evidence_id}': requirement review is not valid for claim approval`;
      throw new KernelValidationError(message, [message], "REVIEW_KIND_NOT_APPLICABLE");
    }
    const unsupported = candidateReviews.filter((decision) => decision.outcome !== "approve");
    if (unsupported.length > 0) {
      const kinds = [...new Set(unsupported.map((decision) => decision.review_kind))].sort();
      throw new KernelValidationError(
        `evidence ${pythonQuoted(candidate.evidence_id)}: unsupported reviewer disagreement/rejection in ${pythonStringList(kinds)}; approval fails closed`,
      );
    }
    if (structuralPolicyBlocked(candidate.source.structural_flags)) {
      throw new KernelValidationError(`evidence ${pythonQuoted(candidate.evidence_id)}: blocked structural policy cannot be approved`);
    }
    const factPolicy = candidate.source.structural_flags.effective_fact_policy;
    if (factPolicy === "F3") {
      const message = `evidence '${candidate.evidence_id}': fact policy F3 requires parser-revalidated current freshness proof before approval`;
      throw new KernelValidationError(message, [message], "F3_CURRENT_VERIFICATION_REQUIRED");
    }
    if (factPolicy === "F4" || factPolicy === "F5") {
      const message = `evidence '${candidate.evidence_id}': fact policy ${factPolicy} is unapprovable without a confirmed fact state`;
      const code = factPolicy === "F4" ? "F4_UNCONFIRMED_FACT" : "F5_UNSUPPORTED_FACT";
      throw new KernelValidationError(message, [message], code);
    }
    if (candidate.claim_mode === "extractive" && candidate.unresolved_questions.length > 0) {
      const message = `evidence '${candidate.evidence_id}': extractive approval cannot proceed with unresolved questions`;
      throw new KernelValidationError(message, [message], "EXTRACTIVE_UNRESOLVED_QUESTIONS");
    }
  }
  return byEvidence;
}

function confirmationRequestsFromNormalized(
  runId: string,
  evidence: NormalizedEvidenceInput,
  reviews: ReviewDecisionIR,
  approvedSafeClaims: Readonly<Record<string, string>>,
  outputMode: ApprovalOutputMode,
): readonly ConfirmationRequest[] {
  const byEvidence = approvalPreflight(evidence, reviews);
  const requests: ConfirmationRequest[] = [];
  for (const candidate of evidence.candidates) {
    const candidateReviews = byEvidence.get(candidate.evidence_id) ?? [];
    const reasons: ConfirmationReason[] = [];
    if (candidate.source.structural_flags.effective_disclosure_policy === "P2") reasons.push("p2_disclosure");
    if (candidate.claim_mode === "reviewed-semantic" && candidate.unresolved_questions.length > 0) {
      reasons.push("candidate_unresolved_questions");
    }
    if (candidateReviews.some((review) => (
      review.review_kind !== "requirement"
      && (review.user_confirmation_required || review.questions.length > 0)
    ))) {
      reasons.push("reviewer_confirmation");
    }
    if (reasons.length === 0) continue;
    if (outputMode !== "targeted_application") {
      const message = `evidence '${candidate.evidence_id}': confirmation is only valid for targeted_application output`;
      throw new KernelValidationError(message, [message], "CONFIRMATION_SCOPE_MISMATCH");
    }
    const claimText = claimTextForCandidate(candidate, approvedSafeClaims);
    const privacy = candidateReviews.filter((review) => review.review_kind === "privacy" && review.outcome === "approve");
    if (privacy.length !== 1) {
      throw new KernelValidationError(
        `evidence ${pythonQuoted(candidate.evidence_id)}: confirmation requires exactly one approving privacy review`,
      );
    }
    const privacyReview = privacy[0];
    if (
      privacyReview === undefined
      || privacyReview.disclosure_decision !== "allowed"
      || privacyReview.disclosure_purpose === null
      || (privacyReview.disclosure_audience !== "recruiter" && privacyReview.disclosure_audience !== "hiring_team")
      || (reasons.includes("p2_disclosure") && privacyReview.disclosure_purpose !== "targeted_application")
    ) {
      const message = `evidence '${candidate.evidence_id}': confirmation privacy scope must be recruiter or hiring_team with targeted_application purpose`;
      throw new KernelValidationError(message, [message], "CONFIRMATION_SCOPE_MISMATCH");
    }
    if (privacyReview.approved_safe_claim !== claimText) {
      const message = `evidence '${candidate.evidence_id}': approved_safe_claim does not exactly match all approving reviews`;
      throw new KernelValidationError(message, [message], "REVIEW_CLAIM_BINDING_MISMATCH");
    }
    const request: ConfirmationRequest = Object.freeze({
      schema_version: 1,
      run_id: requiredString(runId, "run_id"),
      evidence_id: candidate.evidence_id,
      claim_digest: claimTextSha256(claimText),
      disclosure_audience: privacyReview.disclosure_audience,
      disclosure_purpose: privacyReview.disclosure_purpose,
      output_mode: "targeted_application",
      reason_codes: Object.freeze([...new Set(reasons)]),
    });
    validateSchemaDocument(request, "confirmation");
    requests.push(request);
  }
  return Object.freeze(requests);
}

export function deriveConfirmationRequests(
  runId: string,
  evidenceInput: unknown,
  reviewsValue: unknown,
  options: Pick<ApproveClaimsOptions, "approvedSafeClaims" | "outputMode"> = {},
): readonly ConfirmationRequest[] {
  const evidence = normalizeEvidenceInput(evidenceInput);
  const reviews = normalizeReviewDecisions(reviewsValue);
  const approvedSafeClaims = normalizeStringMap(options.approvedSafeClaims, "approved_safe_claims");
  return confirmationRequestsFromNormalized(
    runId,
    evidence,
    reviews,
    approvedSafeClaims,
    options.outputMode ?? "targeted_application",
  );
}

export function confirmationClaimText(
  request: ConfirmationRequest,
  evidenceInput: unknown,
  options: Pick<ApproveClaimsOptions, "approvedSafeClaims"> = {},
): string {
  const evidence = normalizeEvidenceInput(evidenceInput);
  const candidate = evidence.candidates.find((item) => item.evidence_id === request.evidence_id);
  if (candidate === undefined) throw new KernelValidationError("confirmation request references unknown evidence");
  const approvedSafeClaims = normalizeStringMap(options.approvedSafeClaims, "approved_safe_claims");
  const claimText = claimTextForCandidate(candidate, approvedSafeClaims);
  if (claimTextSha256(claimText) !== request.claim_digest) {
    throw new KernelValidationError("confirmation request claim digest does not match exact claim text");
  }
  return claimText;
}

export function validateConfirmationReceipt(
  request: ConfirmationRequest,
  receiptValue: unknown,
): ConfirmationReceipt {
  validateSchemaDocument(request, "confirmation");
  const receipt = normalizeConfirmationReceipt(receiptValue, 0);
  const requestShape = canonicalJson({
    schema_version: request.schema_version,
    run_id: request.run_id,
    evidence_id: request.evidence_id,
    claim_digest: request.claim_digest,
    disclosure_audience: request.disclosure_audience,
    disclosure_purpose: request.disclosure_purpose,
    output_mode: request.output_mode,
    reason_codes: request.reason_codes,
  });
  const receiptShape = canonicalJson({
    schema_version: receipt.schema_version,
    run_id: receipt.run_id,
    evidence_id: receipt.evidence_id,
    claim_digest: receipt.claim_digest,
    disclosure_audience: receipt.disclosure_audience,
    disclosure_purpose: receipt.disclosure_purpose,
    output_mode: receipt.output_mode,
    reason_codes: receipt.reason_codes,
  });
  if (requestShape !== receiptShape) {
    throw new KernelValidationError("confirmation receipt does not match its exact same-run request");
  }
  return receipt;
}

export function approveClaims(
  evidenceInput: unknown,
  reviews: unknown,
  options: ApproveClaimsOptions = {},
): ApprovedClaimsIR {
  const evidence = normalizeEvidenceInput(evidenceInput);
  const reviewIR = normalizeReviewDecisions(reviews);
  const approvedSafeClaims = normalizeStringMap(options.approvedSafeClaims, "approved_safe_claims");
  if (Object.hasOwn(options, "userConfirmations") || Object.hasOwn(options, "user_confirmations")) {
    throw new KernelValidationError(
      "raw user confirmations are not accepted; use same-run UI confirmation receipts",
      undefined,
      "UNTRUSTED_USER_CONFIRMATION",
    );
  }
  const outputMode = options.outputMode ?? "targeted_application";
  const confirmationReceipts = normalizeConfirmationReceipts(options.confirmationReceipts);
  const expectedConfirmationRequests = confirmationRequestsFromNormalized(
    options.runId ?? "",
    evidence,
    reviewIR,
    approvedSafeClaims,
    outputMode,
  );
  const expectedByEvidence = new Map(expectedConfirmationRequests.map((request) => [request.evidence_id, request]));
  const confirmedEvidenceIds = new Set<string>();
  for (const receipt of confirmationReceipts) {
    const request = expectedByEvidence.get(receipt.evidence_id);
    if (request === undefined) {
      throw new KernelValidationError(
        `confirmation receipt references unexpected evidence ${pythonQuoted(receipt.evidence_id)}`,
        undefined,
        "CONFIRMATION_RECEIPT_MISMATCH",
      );
    }
    validateConfirmationReceipt(request, receipt);
    confirmedEvidenceIds.add(receipt.evidence_id);
  }
  for (const request of expectedConfirmationRequests) {
    if (confirmedEvidenceIds.has(request.evidence_id)) continue;
    const p2 = request.reason_codes.includes("p2_disclosure");
    const message = p2
      ? `evidence '${request.evidence_id}': P2 approval requires a same-run user confirmation receipt`
      : `evidence '${request.evidence_id}': required same-run user confirmation receipt is missing`;
    throw new KernelValidationError(
      message,
      [message],
      p2 ? "P2_CONFIRMATION_REQUIRED" : "CONFIRMATION_RECEIPT_REQUIRED",
    );
  }
  const byEvidence = new Map<string, ReviewDecision[]>();
  if (evidence.unresolved_questions.length > 0) {
    const message = `normalized evidence input '${evidence.input_id}' has unresolved questions; approval fails closed until revalidated`;
    throw new KernelValidationError(message, [message], "EVIDENCE_INPUT_UNRESOLVED_QUESTIONS");
  }
  for (const decision of reviewIR.decisions) {
    const existing = byEvidence.get(decision.evidence_id) ?? [];
    existing.push(decision);
    byEvidence.set(decision.evidence_id, existing);
  }
  const knownIds = new Set(evidence.candidates.map((candidate) => candidate.evidence_id));
  const unknown = [...byEvidence.keys()].filter((id) => !knownIds.has(id)).sort();
  if (unknown.length > 0) {
    throw new KernelValidationError(`review decisions reference unknown evidence IDs: ${JSON.stringify(unknown)}`);
  }

  const claims: ApprovedClaimIR[] = [];
  for (const candidate of evidence.candidates) {
    const candidateReviews = byEvidence.get(candidate.evidence_id) ?? [];
    const unsupported = candidateReviews.filter((decision) => decision.outcome !== "approve");
    if (unsupported.length > 0) {
      const kinds = [...new Set(unsupported.map((decision) => decision.review_kind))].sort();
      throw new KernelValidationError(
        `evidence ${pythonQuoted(candidate.evidence_id)}: unsupported reviewer disagreement/rejection in ${pythonStringList(kinds)}; approval fails closed`,
      );
    }
    if (structuralPolicyBlocked(candidate.source.structural_flags)) {
      throw new KernelValidationError(`evidence ${pythonQuoted(candidate.evidence_id)}: blocked structural policy cannot be approved`);
    }
    const factPolicy = candidate.source.structural_flags.effective_fact_policy;
    if (factPolicy === "F3") {
      const message = `evidence '${candidate.evidence_id}': fact policy F3 requires parser-revalidated current freshness proof before approval`;
      throw new KernelValidationError(message, [message], "F3_CURRENT_VERIFICATION_REQUIRED");
    }
    if (factPolicy === "F4" || factPolicy === "F5") {
      const message = `evidence '${candidate.evidence_id}': fact policy ${factPolicy} is unapprovable without a confirmed fact state`;
      const code = factPolicy === "F4" ? "F4_UNCONFIRMED_FACT" : "F5_UNSUPPORTED_FACT";
      throw new KernelValidationError(message, [message], code);
    }
    if (candidate.claim_mode === "extractive" && candidate.unresolved_questions.length > 0) {
      const message = `evidence '${candidate.evidence_id}': extractive approval cannot proceed with unresolved questions`;
      throw new KernelValidationError(message, [message], "EXTRACTIVE_UNRESOLVED_QUESTIONS");
    }

    let claimText: string;
    let basis: ApprovalBasis;
    let reviewerDecisionIds: readonly string[];
    let disclosure: DisclosureDecision;
    let audience: DisclosureAudience | null;
    let purpose: string | null;
    let contributionQualifiers: readonly ContributionQualifier[];
    let metricQualifiers: readonly MetricQualifier[];
    if (candidate.claim_mode === "extractive") {
      claimText = normalizeExtractiveClaim(
        candidate.source.exact_quote,
        approvedSafeClaims[candidate.evidence_id] ?? candidate.proposed_claim,
      );
      basis = "mechanical";
      reviewerDecisionIds = Object.freeze([]);
      disclosure = "allowed";
      audience = "recruiter";
      purpose = "resume evidence";
      contributionQualifiers = Object.freeze(candidate.contribution_qualifiers.map((text) => Object.freeze({
        text,
        scope: null,
        actor: null,
      })));
      metricQualifiers = Object.freeze(candidate.metric_qualifiers.map((text) => Object.freeze({
        text,
        name: null,
        value: null,
        unit: null,
        qualifier: null,
      })));
      const privacy = candidateReviews.filter((decision) => decision.review_kind === "privacy");
      if (candidate.source.structural_flags.effective_disclosure_policy === "P2") {
        const privacyReview = privacy[0];
        if (privacy.length !== 1 || privacyReview === undefined || privacyReview.outcome !== "approve") {
          throw new KernelValidationError(
            `evidence ${JSON.stringify(candidate.evidence_id)}: P2 extractive disclosure requires one approving privacy review`,
          );
        }
        if (privacyReview.disclosure_decision !== "allowed") {
          throw new KernelValidationError(`evidence ${JSON.stringify(candidate.evidence_id)}: privacy review did not allow disclosure`);
        }
        if (privacyReview.approved_safe_claim !== claimText) {
          const message = `evidence '${candidate.evidence_id}': approved_safe_claim does not exactly match all approving reviews`;
          throw new KernelValidationError(message, [message], "REVIEW_CLAIM_BINDING_MISMATCH");
        }
        if (!confirmedEvidenceIds.has(candidate.evidence_id)) {
          const message = `evidence '${candidate.evidence_id}': P2 approval requires a same-run user confirmation receipt`;
          throw new KernelValidationError(message, [message], "P2_CONFIRMATION_REQUIRED");
        }
        basis = "user_confirmed";
        reviewerDecisionIds = Object.freeze([privacyReview.review_id]);
        disclosure = privacyReview.disclosure_decision;
        audience = privacyReview.disclosure_audience;
        purpose = privacyReview.disclosure_purpose;
      }
    } else {
      const selected = new Map<(typeof REQUIRED_REVIEW_KINDS)[number], ReviewDecision>();
      for (const kind of REQUIRED_REVIEW_KINDS) {
        const matches = candidateReviews.filter((decision) => decision.review_kind === kind);
        if (matches.length !== 1) {
          throw new KernelValidationError(
            `evidence ${JSON.stringify(candidate.evidence_id)}: reviewed-semantic approval requires exactly one ${kind} review`,
          );
        }
        const review = matches[0];
        if (review === undefined || review.outcome !== "approve") {
          throw new KernelValidationError(
            `evidence ${JSON.stringify(candidate.evidence_id)}: ${kind} review did not approve; disagreement fails closed`,
          );
        }
        selected.set(kind, review);
      }
      const reviewerIds = new Set([...selected.values()].map((decision) => decision.reviewer_id));
      if (reviewerIds.size !== REQUIRED_REVIEW_KINDS.length) {
        throw new KernelValidationError(
          `evidence ${JSON.stringify(candidate.evidence_id)}: evidence, contribution/metric, and privacy reviewers must be independent`,
        );
      }
      const privacyReview = selected.get("privacy");
      if (privacyReview === undefined || privacyReview.disclosure_decision !== "allowed") {
        throw new KernelValidationError(`evidence ${JSON.stringify(candidate.evidence_id)}: privacy reviewer did not allow disclosure`);
      }
      claimText = approvedSafeClaims[candidate.evidence_id] ?? "";
      if (claimText.length === 0) {
        throw new KernelValidationError(
          `evidence ${JSON.stringify(candidate.evidence_id)}: reviewed-semantic approval requires exact approved_safe_claim`,
        );
      }
      if ([...selected.values()].some((review) => review.approved_safe_claim !== claimText)) {
        const message = `evidence '${candidate.evidence_id}': approved_safe_claim does not exactly match all approving reviews`;
        throw new KernelValidationError(message, [message], "REVIEW_CLAIM_BINDING_MISMATCH");
      }
      const qualifierReview = selected.get("contribution_metric");
      if (qualifierReview === undefined) {
        throw new KernelValidationError("required contribution/metric review selection became inconsistent");
      }
      contributionQualifiers = qualifierReview.contribution_qualifiers;
      metricQualifiers = qualifierReview.metric_qualifiers;
      const confirmationReviews = [...selected.values()].filter((decision) => (
        decision.user_confirmation_required || decision.questions.length > 0
      ));
      const needsConfirmation = candidate.unresolved_questions.length > 0
        || candidate.source.structural_flags.effective_disclosure_policy === "P2"
        || confirmationReviews.length > 0;
      const confirmed = confirmedEvidenceIds.has(candidate.evidence_id);
      if (needsConfirmation && !confirmed) {
        const message = `evidence '${candidate.evidence_id}': required same-run user confirmation receipt is missing`;
        throw new KernelValidationError(message, [message], "CONFIRMATION_RECEIPT_REQUIRED");
      }
      basis = confirmed ? "user_confirmed" : "independent_review";
      reviewerDecisionIds = Object.freeze(REQUIRED_REVIEW_KINDS.map((kind) => {
        const decision = selected.get(kind);
        if (decision === undefined) throw new KernelValidationError("required review selection became inconsistent");
        return decision.review_id;
      }));
      disclosure = privacyReview.disclosure_decision;
      audience = privacyReview.disclosure_audience;
      purpose = privacyReview.disclosure_purpose;
    }

    claims.push(Object.freeze({
      claim_id: `claim.${candidate.evidence_id}`,
      origin_evidence_ids: Object.freeze([candidate.evidence_id]),
      approved_safe_claim: claimText,
      approval_basis: basis,
      reviewer_decision_ids: reviewerDecisionIds,
      claim_mode: candidate.claim_mode,
      contribution_qualifiers: contributionQualifiers,
      metric_qualifiers: metricQualifiers,
      disclosure_decision: disclosure,
      disclosure_audience: audience,
      disclosure_purpose: purpose,
    }));
  }
  return normalizeApprovedClaims({ schema_version: 1, claims });
}

export function lockApprovedClaims(
  approvedClaims: unknown,
  finalClaims?: Readonly<Record<string, string>>,
): ApprovedClaimsIR {
  const value = normalizeApprovedClaims(approvedClaims);
  if (finalClaims !== undefined) {
    const submitted = record(finalClaims, "final_claims");
    const expected = new Map(value.claims.map((claim) => [claim.claim_id, claim.approved_safe_claim]));
    const submittedIds = Object.keys(submitted);
    const unknown = submittedIds.filter((claimId) => !expected.has(claimId)).sort();
    const missing = [...expected.keys()].filter((claimId) => !Object.hasOwn(submitted, claimId)).sort();
    if (unknown.length > 0 || missing.length > 0) {
      const issues: string[] = [];
      if (unknown.length > 0) issues.push(`unknown final claim IDs: ${pythonStringList(unknown)}`);
      if (missing.length > 0) issues.push(`missing final claim IDs: ${pythonStringList(missing)}`);
      throw new KernelValidationError("final claim set is not closed over approved claims", issues);
    }
    const mismatches = [...expected].filter(([claimId, text]) => submitted[claimId] !== text).map(([claimId]) => claimId);
    if (mismatches.length > 0) {
      throw new KernelValidationError(
        `final claim text must exactly equal approved_safe_claim for IDs: ${pythonStringList(mismatches)}`,
      );
    }
  }
  const serialized = JSON.stringify(value);
  if (serialized === undefined) throw new KernelValidationError("approved claims are not JSON serializable");
  return normalizeApprovedClaims(JSON.parse(serialized) as unknown);
}

export async function revalidateApprovalSources(sourceRoot: string, evidenceInput: unknown): Promise<NormalizedEvidenceInput> {
  const evidence = normalizeEvidenceInput(evidenceInput);
  for (const candidate of evidence.candidates) {
    await revalidateSourceReference(sourceRoot, candidate.source);
  }
  return evidence;
}

function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") {
    const serialized = JSON.stringify(value);
    if (serialized === undefined) throw new KernelValidationError("canonical JSON string serialization failed");
    return serialized;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new KernelValidationError("canonical JSON cannot contain a non-finite number");
    const serialized = JSON.stringify(value);
    if (serialized === undefined) throw new KernelValidationError("canonical JSON number serialization failed");
    return serialized;
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  throw new KernelValidationError("canonical JSON accepts only JSON-compatible values");
}

export function canonicalJsonStringify(value: unknown): string {
  return canonicalJson(value);
}

export function canonicalJsonSha256(value: unknown): `sha256:${string}` {
  return `sha256:${createHash("sha256").update(canonicalJson(value), "utf8").digest("hex")}`;
}

function uniqueSorted(values: readonly string[]): readonly string[] {
  return Object.freeze([...new Set(values)].sort());
}

interface NormalizedApprovalOptions {
  readonly approvedSafeClaims: Readonly<Record<string, string>>;
  readonly confirmationReceipts: readonly ConfirmationReceipt[];
  readonly runId?: string;
  readonly outputMode: ApprovalOutputMode;
}

function normalizeApprovalOptions(options: ApproveClaimsOptions): NormalizedApprovalOptions {
  return Object.freeze({
    approvedSafeClaims: normalizeStringMap(options.approvedSafeClaims, "approved_safe_claims"),
    confirmationReceipts: normalizeConfirmationReceipts(options.confirmationReceipts),
    ...(options.runId === undefined ? {} : { runId: requiredString(options.runId, "run_id") }),
    outputMode: options.outputMode ?? "targeted_application",
  });
}

function digestPayload(
  runId: string,
  evidence: NormalizedEvidenceInput,
  reviews: ReviewDecisionIR,
  options: NormalizedApprovalOptions,
  evidenceIds: readonly string[],
  reviewDecisionIds: readonly string[],
  claimIds: readonly string[],
  approvedClaims: ApprovedClaimsIR,
): Readonly<Record<string, unknown>> {
  return Object.freeze({
    schema_version: 1,
    run_id: runId,
    evidence_input_id: evidence.input_id,
    evidence_ids: evidenceIds,
    review_decision_ids: reviewDecisionIds,
    claim_ids: claimIds,
    evidence_input: evidence,
    review_decisions: reviews,
    approval_inputs: Object.freeze({
      approved_safe_claims: options.approvedSafeClaims,
      confirmation_receipts: options.confirmationReceipts,
      output_mode: options.outputMode,
    }),
    approved_claims: approvedClaims,
  });
}

export function createApprovalLock(
  runId: string,
  evidenceInput: unknown,
  reviews: unknown,
  approvedClaims: unknown,
  options: ApproveClaimsOptions = {},
): ApprovalLock {
  const normalizedRunId = requiredString(runId, "run_id");
  const evidence = normalizeEvidenceInput(evidenceInput);
  const reviewIR = normalizeReviewDecisions(reviews);
  const normalizedOptions = normalizeApprovalOptions({ ...options, runId: normalizedRunId });
  const recomputed = approveClaims(evidence, reviewIR, normalizedOptions);
  const approved = lockApprovedClaims(approvedClaims);
  if (canonicalJson(recomputed) !== canonicalJson(approved)) {
    throw new KernelValidationError(
      "approved claims do not exactly equal the deterministic result recomputed from evidence, reviews, and confirmations",
    );
  }
  const evidenceIds = uniqueSorted(evidence.candidates.map((candidate) => candidate.evidence_id));
  const reviewDecisionIds = uniqueSorted(reviewIR.decisions.map((decision) => decision.review_id));
  const claimIds = uniqueSorted(approved.claims.map((claim) => claim.claim_id));
  const knownEvidence = new Set(evidenceIds);
  const knownReviews = new Set(reviewDecisionIds);
  for (const claim of approved.claims) {
    const missingOrigins = claim.origin_evidence_ids.filter((id) => !knownEvidence.has(id));
    if (missingOrigins.length > 0) {
      throw new KernelValidationError(
        `approved claim ${JSON.stringify(claim.claim_id)} has missing origin evidence IDs: ${JSON.stringify(missingOrigins)}`,
      );
    }
    const missingReviews = claim.reviewer_decision_ids.filter((id) => !knownReviews.has(id));
    if (missingReviews.length > 0) {
      throw new KernelValidationError(
        `approved claim ${JSON.stringify(claim.claim_id)} has unknown reviewer decision IDs: ${JSON.stringify(missingReviews)}`,
      );
    }
  }
  const digest = canonicalJsonSha256(digestPayload(
    normalizedRunId,
    evidence,
    reviewIR,
    normalizedOptions,
    evidenceIds,
    reviewDecisionIds,
    claimIds,
    approved,
  ));
  return Object.freeze({
    schema_version: 1,
    backend: "typescript",
    run_id: normalizedRunId,
    evidence_input_id: evidence.input_id,
    evidence_ids: evidenceIds,
    review_decision_ids: reviewDecisionIds,
    claim_ids: claimIds,
    digest,
  });
}

export function approveAndLockClaims(
  runId: string,
  evidenceInput: unknown,
  reviews: unknown,
  options: ApproveClaimsOptions = {},
): ApproveAndLockResult {
  const boundOptions = { ...options, runId };
  const approvedClaims = approveClaims(evidenceInput, reviews, boundOptions);
  const approvalLock = createApprovalLock(runId, evidenceInput, reviews, approvedClaims, boundOptions);
  return Object.freeze({
    backend: "typescript",
    approved_claims: approvedClaims,
    approval_lock: approvalLock,
  });
}

function normalizeApprovalLock(value: unknown): ApprovalLock {
  const lock = record(value, "approval_lock");
  const allowedKeys = new Set([
    "schema_version",
    "backend",
    "run_id",
    "evidence_input_id",
    "evidence_ids",
    "review_decision_ids",
    "claim_ids",
    "digest",
  ]);
  const extras = Object.keys(lock).filter((key) => !allowedKeys.has(key));
  if (extras.length > 0) throw new KernelValidationError(`approval_lock contains unknown fields: ${JSON.stringify(extras.sort())}`);
  if (lock.schema_version !== 1) throw new KernelValidationError("approval_lock.schema_version must equal 1");
  if (lock.backend !== "typescript") throw new KernelValidationError("approval_lock.backend must equal typescript");
  const digest = requiredString(lock.digest, "approval_lock.digest");
  if (!SHA256_PATTERN.test(digest)) throw new KernelValidationError("approval_lock.digest must be sha256:<64 lowercase hex>");
  const evidenceIds = stringArray(lock.evidence_ids, "approval_lock.evidence_ids");
  const reviewDecisionIds = stringArray(lock.review_decision_ids, "approval_lock.review_decision_ids");
  const claimIds = stringArray(lock.claim_ids, "approval_lock.claim_ids");
  if (evidenceIds.length === 0 || claimIds.length === 0) {
    throw new KernelValidationError("approval_lock evidence_ids and claim_ids must not be empty");
  }
  for (const [label, ids] of [["evidence_ids", evidenceIds], ["review_decision_ids", reviewDecisionIds], ["claim_ids", claimIds]] as const) {
    const canonical = uniqueSorted(ids);
    if (canonical.length !== ids.length || canonical.some((id, index) => id !== ids[index])) {
      throw new KernelValidationError(`approval_lock.${label} must be unique and sorted`);
    }
  }
  return Object.freeze({
    schema_version: 1,
    backend: "typescript",
    run_id: requiredString(lock.run_id, "approval_lock.run_id"),
    evidence_input_id: requiredString(lock.evidence_input_id, "approval_lock.evidence_input_id"),
    evidence_ids: evidenceIds,
    review_decision_ids: reviewDecisionIds,
    claim_ids: claimIds,
    digest: digest as `sha256:${string}`,
  });
}

export function verifyApprovalLock(
  runId: string,
  lockValue: unknown,
  evidenceInput: unknown,
  reviews: unknown,
  approvedClaims: unknown,
  options: ApproveClaimsOptions = {},
): ApprovalLock {
  const normalizedRunId = requiredString(runId, "run_id");
  const lock = normalizeApprovalLock(lockValue);
  if (lock.run_id !== normalizedRunId) {
    throw new KernelValidationError("approval lock belongs to a different run");
  }
  const evidence = normalizeEvidenceInput(evidenceInput);
  const reviewIR = normalizeReviewDecisions(reviews);
  const normalizedOptions = normalizeApprovalOptions({ ...options, runId: normalizedRunId });
  const recomputed = approveClaims(evidence, reviewIR, normalizedOptions);
  const approved = lockApprovedClaims(approvedClaims);
  if (canonicalJson(recomputed) !== canonicalJson(approved)) {
    throw new KernelValidationError(
      "approved claims do not exactly equal the deterministic result recomputed from evidence, reviews, and confirmations",
    );
  }
  const evidenceIds = uniqueSorted(evidence.candidates.map((candidate) => candidate.evidence_id));
  const reviewDecisionIds = uniqueSorted(reviewIR.decisions.map((decision) => decision.review_id));
  const claimIds = uniqueSorted(approved.claims.map((claim) => claim.claim_id));
  if (evidence.input_id !== lock.evidence_input_id) {
    throw new KernelValidationError("approval lock evidence input ID does not match the compose payload");
  }
  for (const [label, actual, expectedIds] of [
    ["evidence IDs", evidenceIds, lock.evidence_ids],
    ["review decision IDs", reviewDecisionIds, lock.review_decision_ids],
    ["claim IDs", claimIds, lock.claim_ids],
  ] as const) {
    if (actual.length !== expectedIds.length || actual.some((id, index) => id !== expectedIds[index])) {
      throw new KernelValidationError(`approval lock ${label} do not match the compose payload`);
    }
  }
  const expected = canonicalJsonSha256(digestPayload(
    lock.run_id,
    evidence,
    reviewIR,
    normalizedOptions,
    lock.evidence_ids,
    lock.review_decision_ids,
    lock.claim_ids,
    approved,
  ));
  if (expected !== lock.digest) {
    throw new KernelValidationError(
      "approval lock digest does not match the exact evidence, reviews, confirmations, and approved claims",
    );
  }
  return lock;
}
