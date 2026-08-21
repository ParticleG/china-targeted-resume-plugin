import type { ConfirmationReceipt } from "../kernel/approval.ts";
import {
  authorizeReviewedSemantic,
  createRunPrivacyState,
  summarizePrivacyState,
  type PrivacyStatusSummary,
  type ReviewedSemanticAuthorizationInput,
  type RunPrivacyState,
} from "./privacy/index.ts";

export const RESUME_TOOL_NAMES = [
  "resume_discover_structure",
  "resume_read_source_slice",
  "resume_validate_source_map",
  "resume_validate_role_ir",
  "resume_validate_evidence_ir",
  "resume_lock_approved_claims",
  "resume_compose_variants",
  "resume_render_variants",
  "resume_inspect_variants",
] as const;

export type ResumeToolName = (typeof RESUME_TOOL_NAMES)[number];

export interface VariantStatusSummary {
  readonly variant: string;
  readonly targetPages: number;
  readonly actualPages?: number;
  readonly auditSuccess: boolean;
  readonly pdfSuccess: boolean;
}

export interface ManifestStatusSummary {
  readonly schemaVersion: number;
  readonly variantCount: number;
  readonly variants: readonly VariantStatusSummary[];
}

export interface SourcePolicySpan {
  readonly path: string;
  readonly kind: "section" | "block";
  readonly sourceHash: `sha256:${string}`;
  readonly startLine: number;
  readonly endLine: number;
  readonly effectivePolicy: string;
  readonly ancestorPolicies: readonly string[];
  readonly headingAncestry: readonly string[];
  readonly blockedByPolicy: boolean;
}

export interface SourcePolicyIndex {
  readonly runId: string;
  readonly digest: `sha256:${string}`;
  readonly spans: readonly SourcePolicySpan[];
}

export interface SourcePolicySummary {
  readonly digest: `sha256:${string}`;
  readonly entryCount: number;
}

export class SourcePolicyStateError extends Error {
  readonly code: "SOURCE_POLICY_REQUIRED" | "SOURCE_POLICY_FORBIDDEN" | "SOURCE_POLICY_INVALID";

  constructor(code: SourcePolicyStateError["code"], message: string) {
    super(message);
    this.name = "SourcePolicyStateError";
    this.code = code;
  }
}

export interface EvidenceValidationReceipt {
  readonly runId: string;
  readonly sourceMapDigest: `sha256:${string}`;
  readonly candidateCount: number;
  readonly proposalCount: number;
  readonly unresolvedQuestionCount: number;
  readonly nonCandidateOwnerCount: number;
  readonly requiresReviewedSemantic: boolean;
  readonly profileFieldMarker?: string;
  readonly inputId: string;
  readonly digest: `sha256:${string}`;
}

export interface ValidatedEvidenceBundle {
  readonly sourceMap: unknown;
  readonly evidenceInput: unknown;
  readonly profileFieldMarker?: string;
}

export interface ApprovalReceipt {
  readonly backend: "typescript";
  readonly runId: string;
  readonly digest: `sha256:${string}`;
  readonly evidenceInputId: string;
  readonly evidenceIds: readonly string[];
  readonly reviewDecisionIds: readonly string[];
  readonly claimIds: readonly string[];
  readonly authorizationId?: string;
  readonly reviewerCount: number;
}

export interface ValidatedApprovalBundle {
  readonly approvedClaims: unknown;
  readonly approvalLock: unknown;
  readonly reviews: unknown;
  readonly approvedSafeClaims: Readonly<Record<string, string>>;
  readonly outputMode: string;
  readonly evidenceReceiptDigest: string;
  readonly confirmationReceipts: readonly ConfirmationReceipt[];
  readonly authorizationId?: string;
}

export class ApprovalStateError extends Error {
  readonly code:
    | "EVIDENCE_VALIDATION_REQUIRED"
    | "EVIDENCE_VALIDATION_MISMATCH"
    | "APPROVAL_LOCK_REQUIRED"
    | "APPROVAL_LOCK_MISMATCH";

  constructor(code: ApprovalStateError["code"], message: string) {
    super(message);
    this.name = "ApprovalStateError";
    this.code = code;
  }
}

export interface ResumeRunStatus {
  readonly runId: string;
  readonly privacy: PrivacyStatusSummary;
  readonly completedTools: readonly ResumeToolName[];
  readonly lastTool?: ResumeToolName;
  readonly manifest?: ManifestStatusSummary;
  readonly approval?: ApprovalReceipt;
  readonly evidenceValidation?: EvidenceValidationReceipt;
  readonly sourcePolicy?: SourcePolicySummary;
  readonly confirmationCount: number;
}

interface MutableRunState {
  privacy: RunPrivacyState;
  readonly completedTools: Set<ResumeToolName>;
  lastTool?: ResumeToolName;
  manifest?: ManifestStatusSummary;
  approval?: ApprovalReceipt;
  readonly approvalBundles: Map<string, ValidatedApprovalBundle>;
  readonly approvalReceipts: Map<string, ApprovalReceipt>;
  readonly evidenceBundles: Map<string, ValidatedEvidenceBundle>;
  readonly evidenceReceipts: Map<string, EvidenceValidationReceipt>;
  evidenceValidation?: EvidenceValidationReceipt;
  readonly validatedSourceMaps: Map<string, unknown>;
  readonly confirmationReceipts: Map<string, ConfirmationReceipt>;
  sourcePolicy?: SourcePolicyIndex;
}

const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

function newRunId(): string {
  return `ctr-${crypto.randomUUID()}`;
}

export function validateRunId(value: string): string {
  const runId = value.trim();
  if (!RUN_ID_PATTERN.test(runId)) {
    throw new Error("Run ID must use 1-128 letters, numbers, dots, underscores, or hyphens");
  }
  return runId;
}

function safeReceiptIds(
  values: readonly string[],
  label: string,
  allowEmpty = false,
): readonly string[] {
  if (
    (!allowEmpty && values.length === 0) ||
    values.some((value) => !value || value.length > 256 || /[\r\n\0]/.test(value))
  ) {
    throw new ApprovalStateError("APPROVAL_LOCK_MISMATCH", `${label} contains invalid metadata IDs`);
  }
  return Object.freeze([...values]);
}

function sameIds(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

/**
 * Receipt/status state is metadata-only. Exact validated evidence and approved
 * claims live only in this process-private run map for deterministic handoff;
 * they are never appended to OMP entries, logs, telemetry, or tool results.
 */
export class ResumePluginRuntime {
  readonly #runs = new Map<string, MutableRunState>();
  #activeRunId: string;

  constructor(initialRunId = newRunId()) {
    this.#activeRunId = this.initialize(initialRunId);
  }

  get activeRunId(): string {
    return this.#activeRunId;
  }

  initialize(requestedRunId = newRunId()): string {
    const runId = validateRunId(requestedRunId);
    this.#runs.set(runId, {
      privacy: createRunPrivacyState({ runId }),
      completedTools: new Set<ResumeToolName>(),
      evidenceBundles: new Map<string, ValidatedEvidenceBundle>(),
      evidenceReceipts: new Map<string, EvidenceValidationReceipt>(),
      validatedSourceMaps: new Map<string, unknown>(),
      confirmationReceipts: new Map<string, ConfirmationReceipt>(),
      approvalBundles: new Map<string, ValidatedApprovalBundle>(),
      approvalReceipts: new Map<string, ApprovalReceipt>(),
    });
    this.#activeRunId = runId;
    return runId;
  }

  activate(runId: string): void {
    const normalized = validateRunId(runId);
    if (!this.#runs.has(normalized)) {
      throw new Error(`Unknown resume run ID: ${normalized}`);
    }
    this.#activeRunId = normalized;
  }

  privacyState(runId = this.#activeRunId): RunPrivacyState {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) throw new Error(`Unknown resume run ID: ${normalized}`);
    return run.privacy;
  }

  authorizeReviewedSemantic(runId: string, input: ReviewedSemanticAuthorizationInput): RunPrivacyState {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) throw new Error(`Unknown resume run ID: ${normalized}`);
    run.privacy = authorizeReviewedSemantic(run.privacy, { ...input, runId: normalized });
    this.#activeRunId = normalized;
    return run.privacy;
  }

  recordToolSuccess(tool: ResumeToolName, runId = this.#activeRunId): void {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) return;
    run.completedTools.add(tool);
    run.lastTool = tool;
  }

  recordManifest(manifest: ManifestStatusSummary, runId = this.#activeRunId): void {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) return;
    run.manifest = Object.freeze({
      schemaVersion: manifest.schemaVersion,
      variantCount: manifest.variantCount,
      variants: Object.freeze(manifest.variants.map((variant) => Object.freeze({ ...variant }))),
    });
  }

  recordValidatedSourceMap(
    digest: `sha256:${string}`,
    sourceMap: unknown,
    runId = this.#activeRunId,
  ): void {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run || !/^sha256:[a-f0-9]{64}$/.test(digest)) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_INVALID",
        "Validated source-map receipt does not match the active run",
      );
    }
    run.validatedSourceMaps.set(digest, sourceMap);
  }

  validatedSourceMap(digest: string, runId = this.#activeRunId): unknown {
    const normalized = validateRunId(runId);
    const sourceMap = this.#runs.get(normalized)?.validatedSourceMaps.get(digest);
    if (sourceMap === undefined) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_REQUIRED",
        "The requested same-run validated source-map receipt does not exist",
      );
    }
    return sourceMap;
  }

  recordSourcePolicyIndex(index: SourcePolicyIndex, runId = this.#activeRunId): SourcePolicySummary {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (
      !run ||
      index.runId !== normalized ||
      !/^sha256:[a-f0-9]{64}$/.test(index.digest) ||
      index.spans.length === 0
    ) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_INVALID",
        "Validated source-map policy metadata does not match the active run",
      );
    }
    const spans = index.spans.map((span) => {
      const path = span.path.replaceAll("\\", "/").replace(/^\.\/+/, "");
      if (
        !path ||
        path.startsWith("/") ||
        path.split("/").some((part) => part === "..") ||
        (span.kind !== "section" && span.kind !== "block") ||
        !/^sha256:[a-f0-9]{64}$/.test(span.sourceHash) ||
        !Number.isSafeInteger(span.startLine) ||
        !Number.isSafeInteger(span.endLine) ||
        span.startLine < 1 ||
        span.endLine < span.startLine ||
        !span.effectivePolicy
      ) {
        throw new SourcePolicyStateError(
          "SOURCE_POLICY_INVALID",
          "Validated source-map contains invalid policy span metadata",
        );
      }
      return Object.freeze({
        path,
        kind: span.kind,
        sourceHash: span.sourceHash,
        startLine: span.startLine,
        endLine: span.endLine,
        effectivePolicy: span.effectivePolicy,
        ancestorPolicies: Object.freeze([...span.ancestorPolicies]),
        headingAncestry: Object.freeze([...span.headingAncestry]),
        blockedByPolicy: span.blockedByPolicy,
      });
    });
    run.sourcePolicy = Object.freeze({
      runId: normalized,
      digest: index.digest,
      spans: Object.freeze(spans),
    });
    return Object.freeze({ digest: index.digest, entryCount: spans.length });
  }

  sourcePolicyForSlice(
    pathValue: string,
    startLine: number,
    endLine: number,
    sourceMapDigest: string,
    runId = this.#activeRunId,
  ): Readonly<{
    expectedSourceHash: `sha256:${string}`;
    effectivePolicy: string;
    ancestorPolicies: readonly string[];
    blockedByPolicy: boolean;
  }> {
    const normalized = validateRunId(runId);
    const index = this.#runs.get(normalized)?.sourcePolicy;
    if (!index) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_REQUIRED",
        "Source slices require same-run resume_validate_source_map policy metadata",
      );
    }
    if (index.digest !== sourceMapDigest) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_INVALID",
        "Source slice source-map receipt does not match the active validated map",
      );
    }
    const path = pathValue.replaceAll("\\", "/").replace(/^\.\/+/, "");
    const overlapping = index.spans.filter((span) =>
      span.path === path &&
      span.startLine <= endLine &&
      span.endLine >= startLine
    );
    const owning = overlapping.filter((span) =>
      span.kind === "block" &&
      span.startLine <= startLine &&
      span.endLine >= endLine
    );
    if (owning.length === 0) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_REQUIRED",
        "Requested source slice is not fully owned by a validated safe source block",
      );
    }
    const blockedByPolicy = overlapping.some((span) => span.blockedByPolicy);
    if (blockedByPolicy) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_FORBIDDEN",
        "Validated inherited policy forbids this source slice",
      );
    }
    const policies = [...new Set(overlapping.flatMap((span) => [
      span.effectivePolicy,
      ...span.ancestorPolicies,
    ]))].sort();
    const sourceHashes = [...new Set(owning.map((span) => span.sourceHash))];
    if (sourceHashes.length !== 1) {
      throw new SourcePolicyStateError(
        "SOURCE_POLICY_INVALID",
        "Validated source-map ownership has conflicting source hashes",
      );
    }
    return Object.freeze({
      expectedSourceHash: sourceHashes[0]!,
      effectivePolicy: policies.join("+"),
      ancestorPolicies: Object.freeze(policies),
      blockedByPolicy: false,
    });
  }

  recordEvidenceValidation(
    receipt: EvidenceValidationReceipt,
    runId = this.#activeRunId,
  ): EvidenceValidationReceipt {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (
      !run ||
      receipt.runId !== normalized ||
      !receipt.inputId ||
      receipt.inputId.length > 256 ||
      !/^sha256:[a-f0-9]{64}$/.test(receipt.digest) ||
      !/^sha256:[a-f0-9]{64}$/.test(receipt.sourceMapDigest) ||
      !Number.isSafeInteger(receipt.candidateCount) ||
      receipt.candidateCount < 0 ||
      !Number.isSafeInteger(receipt.proposalCount) ||
      receipt.proposalCount < 0 ||
      !Number.isSafeInteger(receipt.unresolvedQuestionCount) ||
      receipt.unresolvedQuestionCount < 0 ||
      !Number.isSafeInteger(receipt.nonCandidateOwnerCount) ||
      receipt.nonCandidateOwnerCount < 0 ||
      typeof receipt.requiresReviewedSemantic !== "boolean"
    ) {
      throw new ApprovalStateError(
        "EVIDENCE_VALIDATION_MISMATCH",
        "Evidence validation receipt metadata does not match the active run",
      );
    }
    const stored = Object.freeze({
      runId: normalized,
      inputId: receipt.inputId,
      digest: receipt.digest,
      sourceMapDigest: receipt.sourceMapDigest,
      candidateCount: receipt.candidateCount,
      proposalCount: receipt.proposalCount,
      unresolvedQuestionCount: receipt.unresolvedQuestionCount,
      nonCandidateOwnerCount: receipt.nonCandidateOwnerCount,
      requiresReviewedSemantic: receipt.requiresReviewedSemantic,
      ...(receipt.profileFieldMarker === undefined
        ? {}
        : { profileFieldMarker: receipt.profileFieldMarker }),
    });
    run.evidenceValidation = stored;
    run.evidenceReceipts.set(stored.digest, stored);
    return stored;
  }

  assertEvidenceValidation(
    receipt: EvidenceValidationReceipt,
    runId = this.#activeRunId,
  ): void {
    const normalized = validateRunId(runId);
    const stored = this.#runs.get(normalized)?.evidenceReceipts.get(receipt.digest);
    if (!stored) {
      throw new ApprovalStateError(
        "EVIDENCE_VALIDATION_REQUIRED",
        "Claim locking requires same-run resume_validate_evidence_ir success",
      );
    }
    if (
      receipt.runId !== stored.runId ||
      receipt.inputId !== stored.inputId ||
      receipt.digest !== stored.digest ||
      receipt.sourceMapDigest !== stored.sourceMapDigest ||
      receipt.candidateCount !== stored.candidateCount ||
      receipt.proposalCount !== stored.proposalCount ||
      receipt.unresolvedQuestionCount !== stored.unresolvedQuestionCount ||
      receipt.nonCandidateOwnerCount !== stored.nonCandidateOwnerCount ||
      receipt.requiresReviewedSemantic !== stored.requiresReviewedSemantic ||
      receipt.profileFieldMarker !== stored.profileFieldMarker
    ) {
      throw new ApprovalStateError(
        "EVIDENCE_VALIDATION_MISMATCH",
        "Claim locking evidence does not match the exact same-run validated evidence IR",
      );
    }
  }

  evidenceReceipt(receiptDigest: string, runId = this.#activeRunId): EvidenceValidationReceipt {
    const normalized = validateRunId(runId);
    const receipt = this.#runs.get(normalized)?.evidenceReceipts.get(receiptDigest);
    if (!receipt) {
      throw new ApprovalStateError(
        "EVIDENCE_VALIDATION_REQUIRED",
        "The requested same-run evidence validation receipt does not exist",
      );
    }
    return receipt;
  }

  recordEvidenceBundle(
    receipt: EvidenceValidationReceipt,
    bundle: ValidatedEvidenceBundle,
    runId = this.#activeRunId,
  ): void {
    this.assertEvidenceValidation(receipt, runId);
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) {
      throw new ApprovalStateError(
        "EVIDENCE_VALIDATION_MISMATCH",
        "Validated evidence bundle does not match the active run",
      );
    }
    run.evidenceBundles.set(receipt.digest, Object.freeze({
      sourceMap: bundle.sourceMap,
      evidenceInput: bundle.evidenceInput,
      ...(bundle.profileFieldMarker === undefined
        ? {}
        : { profileFieldMarker: bundle.profileFieldMarker }),
    }));
  }

  evidenceBundle(receiptDigest: string, runId = this.#activeRunId): ValidatedEvidenceBundle {
    const normalized = validateRunId(runId);
    const bundle = this.#runs.get(normalized)?.evidenceBundles.get(receiptDigest);
    if (!bundle) {
      throw new ApprovalStateError(
        "EVIDENCE_VALIDATION_REQUIRED",
        "This run has no private validated evidence bundle",
      );
    }
    return bundle;
  }

  recordConfirmationReceipt(
    receipt: ConfirmationReceipt,
    runId = this.#activeRunId,
  ): ConfirmationReceipt {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (
      !run ||
      receipt.run_id !== normalized ||
      receipt.confirmed !== true ||
      receipt.confirmed_by !== "interactive_user" ||
      receipt.output_mode !== "targeted_application" ||
      receipt.reason_codes.length === 0 ||
      receipt.reason_codes.some((reason) =>
        !["p2_disclosure", "candidate_unresolved_questions", "reviewer_confirmation"].includes(reason)
      ) ||
      !/^sha256:[a-f0-9]{64}$/.test(receipt.claim_digest) ||
      !receipt.nonce ||
      Number.isNaN(Date.parse(receipt.confirmed_at))
    ) {
      throw new ApprovalStateError(
        "APPROVAL_LOCK_MISMATCH",
        "Confirmation receipt does not match the active run",
      );
    }
    const key = [
      receipt.evidence_id,
      receipt.claim_digest,
      receipt.disclosure_audience,
      receipt.disclosure_purpose,
      receipt.output_mode,
      ...receipt.reason_codes,
    ].join("\u0000");
    run.confirmationReceipts.set(key, Object.freeze({ ...receipt }));
    return receipt;
  }

  confirmationReceipts(runId = this.#activeRunId): readonly ConfirmationReceipt[] {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) {
      throw new ApprovalStateError(
        "APPROVAL_LOCK_MISMATCH",
        "Confirmation receipts do not match an active run",
      );
    }
    return Object.freeze([...run.confirmationReceipts.values()]);
  }

  recordApprovalReceipt(receipt: ApprovalReceipt, runId = this.#activeRunId): ApprovalReceipt {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) throw new ApprovalStateError("APPROVAL_LOCK_MISMATCH", `Unknown resume run ID: ${normalized}`);
    if (
      receipt.runId !== normalized ||
      receipt.backend !== "typescript" ||
      !/^sha256:[a-f0-9]{64}$/.test(receipt.digest) ||
      !receipt.evidenceInputId ||
      receipt.evidenceInputId.length > 256 ||
      receipt.reviewDecisionIds.length !== receipt.reviewerCount ||
      (receipt.authorizationId !== undefined && receipt.authorizationId.length === 0)
    ) {
      throw new ApprovalStateError("APPROVAL_LOCK_MISMATCH", "Approval lock metadata does not match the active run");
    }
    const stored = Object.freeze({
      backend: "typescript" as const,
      runId: normalized,
      digest: receipt.digest,
      evidenceInputId: receipt.evidenceInputId,
      evidenceIds: safeReceiptIds(receipt.evidenceIds, "Evidence lock"),
      reviewDecisionIds: safeReceiptIds(receipt.reviewDecisionIds, "Review lock", true),
      claimIds: safeReceiptIds(receipt.claimIds, "Claim lock"),
      reviewerCount: receipt.reviewerCount,
      ...(receipt.authorizationId === undefined
        ? {}
        : { authorizationId: receipt.authorizationId }),
    });
    run.approval = stored;
    run.approvalReceipts.set(stored.digest, stored);
    return stored;
  }

  approvalReceipt(receiptDigest: string, runId = this.#activeRunId): ApprovalReceipt {
    const normalized = validateRunId(runId);
    const receipt = this.#runs.get(normalized)?.approvalReceipts.get(receiptDigest);
    if (!receipt) {
      throw new ApprovalStateError(
        "APPROVAL_LOCK_REQUIRED",
        "Compose requires a same-run approval receipt created by resume_lock_approved_claims",
      );
    }
    return receipt;
  }

  assertApprovalReceipt(receipt: ApprovalReceipt, runId = this.#activeRunId): void {
    const normalized = validateRunId(runId);
    const stored = this.#runs.get(normalized)?.approvalReceipts.get(receipt.digest);
    if (!stored) {
      throw new ApprovalStateError(
        "APPROVAL_LOCK_REQUIRED",
        "Compose requires a same-run approval receipt created by resume_lock_approved_claims",
      );
    }
    if (
      receipt.backend !== stored.backend ||
      receipt.runId !== stored.runId ||
      receipt.digest !== stored.digest ||
      receipt.evidenceInputId !== stored.evidenceInputId ||
      receipt.reviewerCount !== stored.reviewerCount ||
      receipt.authorizationId !== stored.authorizationId ||
      !sameIds(receipt.evidenceIds, stored.evidenceIds) ||
      !sameIds(receipt.reviewDecisionIds, stored.reviewDecisionIds) ||
      !sameIds(receipt.claimIds, stored.claimIds)
    ) {
      throw new ApprovalStateError(
        "APPROVAL_LOCK_MISMATCH",
        "Compose approval metadata does not match the exact claims locked for this run",
      );
    }
  }

  recordApprovalBundle(
    receipt: ApprovalReceipt,
    bundle: ValidatedApprovalBundle,
    runId = this.#activeRunId,
  ): void {
    this.assertApprovalReceipt(receipt, runId);
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) {
      throw new ApprovalStateError(
        "APPROVAL_LOCK_MISMATCH",
        "Approval bundle does not match the active run",
      );
    }
    run.approvalBundles.set(receipt.digest, Object.freeze({
      approvedClaims: bundle.approvedClaims,
      approvalLock: bundle.approvalLock,
      reviews: bundle.reviews,
      approvedSafeClaims: Object.freeze({ ...bundle.approvedSafeClaims }),
      outputMode: bundle.outputMode,
      evidenceReceiptDigest: bundle.evidenceReceiptDigest,
      ...(bundle.authorizationId === undefined
        ? {}
        : { authorizationId: bundle.authorizationId }),
      confirmationReceipts: Object.freeze([...bundle.confirmationReceipts]),
    }));
  }

  approvalBundle(receiptDigest: string, runId = this.#activeRunId): ValidatedApprovalBundle {
    const normalized = validateRunId(runId);
    const bundle = this.#runs.get(normalized)?.approvalBundles.get(receiptDigest);
    if (!bundle) {
      throw new ApprovalStateError(
        "APPROVAL_LOCK_REQUIRED",
        "The requested same-run private approval bundle does not exist",
      );
    }
    return bundle;
  }

  status(runId = this.#activeRunId): ResumeRunStatus {
    const normalized = validateRunId(runId);
    const run = this.#runs.get(normalized);
    if (!run) throw new Error(`Unknown resume run ID: ${normalized}`);
    const lastTool = run.lastTool;
    const manifest = run.manifest;
    const approval = run.approval;
    const evidenceValidation = run.evidenceValidation;
    const sourcePolicy = run.sourcePolicy === undefined
      ? undefined
      : Object.freeze({
          digest: run.sourcePolicy.digest,
          entryCount: run.sourcePolicy.spans.length,
        });
    return Object.freeze({
      runId: normalized,
      privacy: summarizePrivacyState(run.privacy),
      completedTools: Object.freeze([...run.completedTools]),
      confirmationCount: run.confirmationReceipts.size,
      ...(lastTool === undefined ? {} : { lastTool }),
      ...(manifest === undefined ? {} : { manifest }),
      ...(evidenceValidation === undefined ? {} : { evidenceValidation }),
      ...(sourcePolicy === undefined ? {} : { sourcePolicy }),
      ...(approval === undefined ? {} : { approval }),
    });
  }
}
