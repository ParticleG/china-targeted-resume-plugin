import { lstat } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import {
  approveAndLockClaims,
  canonicalJsonSha256,
  confirmationClaimText,
  deriveConfirmationRequests,
  KernelValidationError,
  revalidateApprovalSources,
  verifyApprovalLock,
  validateConfirmationReceipt,
  normalizeEvidenceInput,
  type ApprovalLock,
  type ApproveClaimsOptions,
  type ApprovalOutputMode,
  type ConfirmationReceipt,
  type ConfirmationRequest,
  type NormalizedEvidenceInput,
} from "../../kernel/approval.ts";
import { SchemaValidationError, validateSchemaDocument } from "../../kernel/schema.ts";
import { SourceIdentityError } from "../../kernel/source-identity.ts";
import {
  ManifestContractError,
  readVariantManifest,
  resolveVariantArtifacts,
  summarizeVariantManifest,
} from "../manifest.ts";
import {
  RESUME_TOOL_NAMES,
  ApprovalStateError,
  SourcePolicyStateError,
  ResumePluginRuntime,
  type ApprovalReceipt,
  type EvidenceValidationReceipt,
  type SourcePolicyIndex,
  type SourcePolicySpan,
  type ResumeToolName,
} from "../runtime.ts";
import {
  KernelBridgeError,
  PythonKernelBridge,
  type JsonObject,
  type JsonValue,
  type StructuredKernelError,
  type KernelRunOptions,
} from "./python-bridge.ts";
import {
  readPrefilteredSourceSlice,
  relativeSourcePath,
  SourceSliceReadError,
} from "./source-slice.ts";

export { RESUME_TOOL_NAMES };
export {
  KernelBridgeError,
  PythonKernelBridge,
  buildPythonKernelInvocation,
  terminateKernelProcessTree,
  type JsonObject,
  type JsonValue,
  type KernelRequest,
  type KernelSpawner,
  type KernelProcess,
  type StructuredKernelError,
} from "./python-bridge.ts";

export interface ResumeToolError {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly operation?: string;
  readonly exitCode?: number;
  readonly kernelType?: string;
}

export interface ResumeToolEnvelope {
  readonly ok: boolean;
  readonly tool: ResumeToolName;
  readonly runId: string;
  readonly data?: JsonValue;
  readonly error?: ResumeToolError;
}

export interface RegisterResumeToolsOptions {
  readonly bridge?: PythonKernelBridge;
}

function normalizeJson(value: unknown): JsonValue {
  let serialized: string | undefined;
  try {
    serialized = JSON.stringify(value);
  } catch {
    // Converted below to the same bounded contract error as undefined values.
  }
  if (serialized === undefined) throw new Error("Tool result is not JSON serializable");
  return JSON.parse(serialized) as JsonValue;
}

function requireJsonObject(value: unknown): JsonObject {
  const normalized = normalizeJson(value);
  if (typeof normalized !== "object" || normalized === null || Array.isArray(normalized)) {
    throw new Error("Tool input must be one JSON object");
  }
  return normalized as JsonObject;
}

function exactlyOnePayloadValue(
  payload: JsonObject,
  keys: readonly string[],
  label: string,
): JsonValue {
  const present = keys.filter((key) => Object.hasOwn(payload, key));
  if (present.length !== 1) {
    throw new KernelValidationError(
      `${label} requires exactly one canonical payload field; duplicate aliases are forbidden`,
    );
  }
  return payload[present[0]!]!;
}


const REVIEWER_WRAPPER_KEYS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  "evidence-reviewer": Object.freeze([
    "contract_version", "agent_role", "mode", "authorization_id", "decision",
    "claim_id", "requirement_ids", "support_finding", "uncertainty_finding",
    "source_reference_ids", "unsupported_elements", "blocking_reasons",
  ]),
  "contribution-reviewer": Object.freeze([
    "contract_version", "agent_role", "mode", "authorization_id", "decision",
    "claim_id", "actor_scope_finding", "contribution_finding", "metric_finding",
    "mismatches", "required_resolution", "blocking_reasons",
  ]),
  "privacy-reviewer": Object.freeze([
    "contract_version", "agent_role", "mode", "authorization_id", "decision",
    "claim_id", "effective_fact_policy", "effective_disclosure_policy",
    "prefilter_status", "permission_status", "request_output_mode", "redactions",
    "blocking_reasons",
  ]),
});

function assertReviewerWrapperShape(wrapper: Record<string, unknown>): void {
  const role = typeof wrapper.agent_role === "string" ? wrapper.agent_role : "";
  const expected = REVIEWER_WRAPPER_KEYS[role];
  if (!expected) {
    throw new KernelValidationError("Reviewed-semantic reviewer wrapper has an unsupported agent_role");
  }
  const actual = Object.keys(wrapper).sort();
  const required = [...expected].sort();
  if (
    actual.length !== required.length ||
    actual.some((key, index) => key !== required[index])
  ) {
    throw new KernelValidationError(
      "Reviewed-semantic reviewer wrapper is missing required fields or contains extras",
    );
  }
  if (wrapper.contract_version !== 1) {
    throw new KernelValidationError("Reviewed-semantic reviewer contract_version must equal 1");
  }
  const arrayFields = role === "evidence-reviewer"
    ? ["requirement_ids", "source_reference_ids", "unsupported_elements", "blocking_reasons"]
    : role === "contribution-reviewer"
      ? ["mismatches", "blocking_reasons"]
      : ["redactions", "blocking_reasons"];
  if (arrayFields.some((field) => !Array.isArray(wrapper[field]))) {
    throw new KernelValidationError("Reviewed-semantic reviewer wrapper array findings are malformed");
  }
}

function approvalReviews(
  payload: JsonObject,
  binding: Readonly<{ mode: "metadata-only" | "reviewed-semantic"; authorizationId?: string }>,
): JsonValue {
  const raw = exactlyOnePayloadValue(
    payload,
    ["review_decisions", "reviews", "review_decision"],
    "Approval reviews",
  );
  const rawRecord = !Array.isArray(raw) && typeof raw === "object" && raw !== null
    ? raw as Record<string, unknown>
    : undefined;
  const canonicalDecisions = rawRecord !== undefined && Array.isArray(rawRecord.decisions)
    ? rawRecord.decisions
    : undefined;
  if (binding.mode === "metadata-only") {
    if (canonicalDecisions?.length === 0) {
      return Object.freeze({ schema_version: 1, decisions: Object.freeze([]) });
    }
    throw new KernelValidationError(
      "Metadata-only mechanical approval accepts only an empty canonical review set",
    );
  }
  if (canonicalDecisions !== undefined) {
    throw new KernelValidationError(
      "Reviewed-semantic reviews require full agent output wrappers, not canonical decisions",
    );
  }
  if (!binding.authorizationId) {
    throw new KernelValidationError(
      "Reviewed-semantic reviews require an active authorization ID",
    );
  }
  const wrappers: readonly unknown[] = Array.isArray(raw)
    ? raw
    : canonicalDecisions ?? (rawRecord?.decision === undefined ? [] : [rawRecord]);
  if (wrappers.length === 0) {
    throw new KernelValidationError(
      "Reviewed-semantic nonempty reviews require full agent output wrappers",
    );
  }
  const roleKinds: Readonly<Record<string, string>> = {
    "evidence-reviewer": "evidence",
    "contribution-reviewer": "contribution_metric",
    "privacy-reviewer": "privacy",
  };
  const decisions = wrappers.map((value, index) => {
    const wrapper = recordValue(value, `review_decisions[${index}]`);
    assertReviewerWrapperShape(wrapper);
    if (
      wrapper.mode !== "reviewed_semantic" ||
      wrapper.authorization_id !== binding.authorizationId ||
      typeof wrapper.agent_role !== "string" ||
      wrapper.decision === undefined
    ) {
      throw new KernelValidationError(
        "Reviewed-semantic review wrapper mode, authorization, role, or decision is invalid",
      );
    }
    if (wrapper.agent_role === "requirement-reviewer") {
      throw new KernelValidationError(
        "Requirement-reviewer decisions cannot enter approved-claim locking",
      );
    }
    const expectedKind = roleKinds[wrapper.agent_role];
    const decision = recordValue(wrapper.decision, `review_decisions[${index}].decision`);
    if (!expectedKind || decision.review_kind !== expectedKind) {
      throw new KernelValidationError(
        "Reviewer agent role does not match nested review_kind",
      );
    }
    return requireJsonObject(decision);
  });
  return Object.freeze({ schema_version: 1, decisions: Object.freeze(decisions) });
}
function optionalScalarMap<T extends boolean | string>(
  value: JsonValue | undefined,
  label: string,
  scalar: "boolean" | "string",
): Readonly<Record<string, T>> | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new KernelValidationError(`${label} must be an object`);
  }
  const entries = Object.entries(value);
  if (entries.some(([, item]) => typeof item !== scalar)) {
    throw new KernelValidationError(`${label} values must be ${scalar}s`);
  }
  return Object.freeze(Object.fromEntries(entries)) as Readonly<Record<string, T>>;
}

class ConfirmationBoundaryError extends Error {
  readonly code:
    | "CALLER_CONFIRMATION_FORBIDDEN"
    | "CONFIRMATION_DECLINED"
    | "CONFIRMATION_UNAVAILABLE";

  constructor(code: ConfirmationBoundaryError["code"], message: string) {
    super(message);
    this.name = "ConfirmationBoundaryError";
    this.code = code;
  }
}

function rejectCallerConfirmations(payload: JsonObject): void {
  if (
    Object.hasOwn(payload, "user_confirmations") ||
    Object.hasOwn(payload, "confirmation_receipts")
  ) {
    throw new ConfirmationBoundaryError(
      "CALLER_CONFIRMATION_FORBIDDEN",
      "Caller-supplied confirmation booleans or receipts cannot unlock claims",
    );
  }
}

function rejectCallerEvidence(payload: JsonObject): void {
  const forbidden = [
    "source_map",
    "source_map_ir",
    "normalized_evidence_input",
    "evidence_input",
    "normalized-evidence-input",
  ];
  if (forbidden.some((key) => Object.hasOwn(payload, key))) {
    throw new ApprovalStateError(
      "EVIDENCE_VALIDATION_MISMATCH",
      "Lock and compose accept only an evidence receipt digest, never caller evidence bodies",
    );
  }
}

function rejectCallerApproval(payload: JsonObject): void {
  const forbidden = [
    "approval_lock",
    "approved_claims",
    "approved_claims_ir",
    "approved-claims",
    "review_decisions",
    "reviews",
    "review_decision",
    "approved_safe_claims",
  ];
  if (forbidden.some((key) => Object.hasOwn(payload, key))) {
    throw new ApprovalStateError(
      "APPROVAL_LOCK_MISMATCH",
      "Compose accepts only an approval receipt digest, never caller approval bodies",
    );
  }
}

function approvalOutputMode(payload: JsonObject): ApprovalOutputMode {
  const request = typeof payload.request === "object" && payload.request !== null && !Array.isArray(payload.request)
    ? payload.request as JsonObject
    : undefined;
  const direct = payload.output_mode;
  const nested = request?.output_mode;
  if (direct !== undefined && nested !== undefined && direct !== nested) {
    throw new KernelValidationError("Approval output_mode conflicts with request.output_mode");
  }
  const mode = direct ?? nested;
  if (
    mode !== "targeted_application" &&
    mode !== "public_portfolio" &&
    mode !== "master_resume"
  ) {
    throw new KernelValidationError("Approval requires one explicit supported output_mode");
  }
  return mode;
}

function approvedSafeClaims(payload: JsonObject): Readonly<Record<string, string>> | undefined {
  return optionalScalarMap<string>(
    payload.approved_safe_claims,
    "approved_safe_claims",
    "string",
  );
}

function confirmationMatches(
  request: ConfirmationRequest,
  receipt: ConfirmationReceipt,
): boolean {
  return (
    receipt.run_id === request.run_id &&
    receipt.evidence_id === request.evidence_id &&
    receipt.claim_digest === request.claim_digest &&
    receipt.disclosure_audience === request.disclosure_audience &&
    receipt.disclosure_purpose === request.disclosure_purpose &&
    receipt.output_mode === request.output_mode &&
    receipt.reason_codes.length === request.reason_codes.length &&
    receipt.reason_codes.every((reason, index) => reason === request.reason_codes[index])
  );
}

function verifiedRuntimeConfirmations(
  runtime: ResumePluginRuntime,
  runId: string,
  requests: readonly ConfirmationRequest[],
): readonly ConfirmationReceipt[] {
  const stored = runtime.confirmationReceipts(runId);
  return Object.freeze(requests.map((request) => {
    const receipt = stored.find((candidate) => confirmationMatches(request, candidate));
    if (!receipt) {
      throw new ConfirmationBoundaryError(
        "CONFIRMATION_UNAVAILABLE",
        "Required same-run confirmation receipt is absent or bound to a different claim",
      );
    }
    return validateConfirmationReceipt(request, receipt);
  }));
}

async function collectConfirmationReceipts(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  runtime: ResumePluginRuntime,
  runId: string,
  evidence: unknown,
  reviews: unknown,
  approvedClaims: Readonly<Record<string, string>> | undefined,
  outputMode: ApprovalOutputMode,
): Promise<readonly ConfirmationReceipt[]> {
  const requests = deriveConfirmationRequests(runId, evidence, reviews, {
    ...(approvedClaims === undefined ? {} : { approvedSafeClaims: approvedClaims }),
    outputMode,
  });
  const receipts: ConfirmationReceipt[] = [];
  const stored = runtime.confirmationReceipts(runId);
  for (const request of requests) {
    const prior = stored.find((candidate) => confirmationMatches(request, candidate));
    if (prior) {
      receipts.push(validateConfirmationReceipt(request, prior));
      continue;
    }
    if (!ctx.hasUI) {
      throw new ConfirmationBoundaryError(
        "CONFIRMATION_UNAVAILABLE",
        "Required claim confirmation needs the interactive OMP UI",
      );
    }
    const exactClaim = confirmationClaimText(request, evidence, {
      ...(approvedClaims === undefined ? {} : { approvedSafeClaims: approvedClaims }),
    });
    const confirmed = await ctx.ui.confirm(
      "Confirm exact resume claim disclosure",
      [
        `Claim: ${exactClaim}`,
        `Audience: ${request.disclosure_audience}`,
        `Purpose: ${request.disclosure_purpose}`,
        `Reasons: ${request.reason_codes.join(", ")}`,
        `Claim digest: ${request.claim_digest}`,
      ].join("\n"),
    );
    if (!confirmed) {
      throw new ConfirmationBoundaryError(
        "CONFIRMATION_DECLINED",
        "User declined the required exact-claim confirmation",
      );
    }
    const receipt = validateConfirmationReceipt(request, {
      ...request,
      confirmed: true,
      confirmed_by: "interactive_user",
      confirmed_at: new Date().toISOString(),
      nonce: crypto.randomUUID(),
    });
    pi.appendEntry("china-targeted-resume/claim-confirmation", receipt);
    runtime.recordConfirmationReceipt(receipt, runId);
    receipts.push(receipt);
  }
  return Object.freeze(receipts);
}

function approvalOptions(
  payload: JsonObject,
  receipts: readonly ConfirmationReceipt[],
  runId: string,
): ApproveClaimsOptions {
  const claims = approvedSafeClaims(payload);
  return {
    ...(claims === undefined ? {} : { approvedSafeClaims: claims }),
    confirmationReceipts: receipts,
    runId,
    outputMode: approvalOutputMode(payload),
  };
}

function approvalReceipt(
  lock: ApprovalLock,
  authorizationId?: string,
): ApprovalReceipt {
  return Object.freeze({
    backend: lock.backend,
    runId: lock.run_id,
    digest: lock.digest,
    evidenceInputId: lock.evidence_input_id,
    evidenceIds: lock.evidence_ids,
    reviewDecisionIds: lock.review_decision_ids,
    claimIds: lock.claim_ids,
    reviewerCount: lock.review_decision_ids.length,
    ...(authorizationId === undefined ? {} : { authorizationId }),
  });
}

function recordValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new KernelValidationError(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function validatedSourceMapResult(result: JsonObject): JsonObject {
  const candidate =
    result.result ??
    Object.freeze(Object.fromEntries(
      Object.entries(result).filter(([key]) => key !== "operation"),
    ));
  return validateSchemaDocument(candidate, "source-map") as JsonObject;
}

function sourcePolicyIndex(runId: string, result: JsonObject): SourcePolicyIndex {
  const sourceMap = validatedSourceMapResult(result);
  const documents = Array.isArray(sourceMap.documents) ? sourceMap.documents : [];
  const documentMetadata = new Map<string, {
    path: string;
    sourceHash: `sha256:${string}`;
    fact: string;
    disclosure: string;
  }>();
  const spans: SourcePolicySpan[] = [];
  for (const value of documents) {
    const document = recordValue(value, "source-map document");
    const documentId = String(document.document_id);
    const path = String(document.path);
    const sourceHash = String(document.source_hash) as `sha256:${string}`;
    const fact = typeof document.document_fact_policy === "string"
      ? document.document_fact_policy
      : "F5";
    const disclosure = typeof document.document_disclosure_policy === "string"
      ? document.document_disclosure_policy
      : "P3";
    documentMetadata.set(documentId, {
      path,
      sourceHash,
      fact,
      disclosure,
    });
  }
  for (const collectionName of ["sections", "blocks"] as const) {
    const collection = Array.isArray(sourceMap[collectionName]) ? sourceMap[collectionName] : [];
    for (const value of collection) {
      const item = recordValue(value, `source-map ${collectionName}`);
      const document = documentMetadata.get(String(item.document_id));
      if (!document) {
        throw new KernelValidationError(
          `${collectionName} entry references an unknown document`,
        );
      }
      const span = recordValue(item.span, `${collectionName} span`);
      const flags = item.structural_flags === undefined
        ? {}
        : recordValue(item.structural_flags, `${collectionName} structural_flags`);
      const fact = typeof flags.effective_fact_policy === "string"
        ? flags.effective_fact_policy
        : document.fact;
      const disclosure = typeof flags.effective_disclosure_policy === "string"
        ? flags.effective_disclosure_policy
        : document.disclosure;
      const headingAncestry = Array.isArray(item.heading_ancestry)
        ? item.heading_ancestry.map(String)
        : [];
      const contactMetadata = /(?:联系|联系方式|邮箱|电子邮件|电话|手机|住址|地址|contact|e-?mail|phone|telephone|address|linkedin)/iu.test(
        [...headingAncestry, String(flags.block_kind ?? "")].join(" "),
      );
      spans.push(Object.freeze({
        path: document.path,
        kind: collectionName === "blocks" ? "block" : "section",
        sourceHash: document.sourceHash,
        startLine: Number(span.start_line),
        endLine: Number(span.end_line),
        effectivePolicy: `${fact}/${disclosure}`,
        ancestorPolicies: Object.freeze([
          document.fact,
          document.disclosure,
          fact,
          disclosure,
        ]),
        headingAncestry: Object.freeze(headingAncestry),
        blockedByPolicy:
          document.fact === "F6" ||
          document.disclosure === "P3" ||
          fact === "F6" ||
          disclosure === "P3" ||
          contactMetadata ||
          [
            "inside_blockquote",
            "inside_fence",
            "inside_html",
            "is_example",
            "is_quoted",
            "is_template",
            "malformed",
            "negative_instruction",
            "secret_content",
            "secret_path",
          ].some((name) => flags[name] === true),
      }));
    }
  }
  const digest = canonicalJsonSha256(sourceMap);
  return Object.freeze({
    runId,
    digest,
    spans: Object.freeze(spans),
  });
}

interface KernelEvidenceBundle {
  readonly sourceMap: JsonObject;
  readonly evidenceInput: NormalizedEvidenceInput;
  readonly profileFieldMarker?: string;
}

function validatedEvidenceBundle(result: JsonObject, input: JsonObject): KernelEvidenceBundle {
  const output =
    result.result !== undefined
      ? recordValue(result.result, "validate-evidence result")
      : Object.fromEntries(Object.entries(result).filter(([key]) => key !== "operation"));
  const evidenceValue = output.evidence_input ?? output.normalized_evidence_input ?? output;
  const sourceMapValue =
    output.source_map ??
    input.source_map ??
    input.source_map_ir;
  if (sourceMapValue === undefined) {
    throw new KernelValidationError("Validated evidence result requires its authoritative source_map");
  }
  const sourceMap = validateSchemaDocument(sourceMapValue, "source-map") as JsonObject;
  const evidenceInput = normalizeEvidenceInput(evidenceValue);
  const profileFieldMarker = typeof output.profile_field_marker === "string"
    ? output.profile_field_marker
    : undefined;
  return Object.freeze({
    sourceMap,
    evidenceInput,
    ...(profileFieldMarker === undefined ? {} : { profileFieldMarker }),
  });
}

function evidenceValidationReceipt(
  runId: string,
  bundle: KernelEvidenceBundle,
): EvidenceValidationReceipt {
  const candidates = bundle.evidenceInput.candidates;
  const proposals = Array.isArray(bundle.sourceMap.proposals)
    ? bundle.sourceMap.proposals
    : [];
  const unresolvedQuestionCount =
    bundle.evidenceInput.unresolved_questions.length +
    candidates.reduce((total, candidate) => total + candidate.unresolved_questions.length, 0);
  const nonCandidateOwnerCount = candidates.filter((candidate) => candidate.owner !== "candidate").length;
  const requiresReviewedSemantic =
    unresolvedQuestionCount > 0 ||
    nonCandidateOwnerCount > 0 ||
    candidates.some((candidate) => candidate.claim_mode === "reviewed-semantic");
  return Object.freeze({
    runId,
    inputId: bundle.evidenceInput.input_id,
    digest: canonicalJsonSha256(bundle.evidenceInput),
    sourceMapDigest: canonicalJsonSha256(bundle.sourceMap),
    candidateCount: candidates.length,
    proposalCount: proposals.length,
    unresolvedQuestionCount,
    nonCandidateOwnerCount,
    requiresReviewedSemantic,
    ...(bundle.profileFieldMarker === undefined
      ? {}
      : { profileFieldMarker: bundle.profileFieldMarker }),
  });
}

function metadataId(value: unknown, label: string): string {
  if (
    typeof value !== "string" ||
    !/^[^\s\0]{1,240}$/u.test(value)
  ) {
    throw new KernelValidationError(`${label} must be one bounded whitespace-free ID`);
  }
  return value;
}

function metadataIdList(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new KernelValidationError(`${label} must be a non-empty ID array`);
  }
  return value.map((item, index) => metadataId(item, `${label}[${index}]`));
}

function assertExactMappingKeys(
  mapping: Record<string, unknown>,
  selected: readonly string[],
  label: string,
): void {
  const keys = Object.keys(mapping);
  keys.forEach((key, index) => metadataId(key, `${label} key ${index}`));
  const expected = [...selected].sort();
  const actual = [...keys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new KernelValidationError(`${label} keys must exactly match selected block IDs`);
  }
}

function assertMetadataOnlyEvidenceRequest(input: JsonObject, sourceMapValue: unknown): void {
  if (
    Object.keys(input).length !== 1 ||
    !Object.hasOwn(input, "materialize_extractive")
  ) {
    throw new KernelValidationError(
      "Metadata-only evidence validation accepts only materialize_extractive selector IDs",
    );
  }
  const materialize = recordValue(input.materialize_extractive, "materialize_extractive");
  const allowedMaterialize = new Set([
    "input_id",
    "block_ids",
    "selected_block_ids",
    "evidence_ids",
    "requirement_ids",
    "profile_field_marker",
  ]);
  if (Object.keys(materialize).some((key) => !allowedMaterialize.has(key))) {
    throw new KernelValidationError("materialize_extractive contains non-metadata fields");
  }
  metadataId(materialize.input_id, "materialize_extractive.input_id");
  const marker = metadataId(
    materialize.profile_field_marker,
    "materialize_extractive.profile_field_marker",
  );
  if (!["name", "summary", "location", "links", "evidence"].includes(marker)) {
    throw new KernelValidationError("profile_field_marker is not an allowed extractive field");
  }
  const selected = metadataIdList(
    materialize.block_ids ?? materialize.selected_block_ids,
    "materialize_extractive.selected_block_ids",
  );
  const sourceMap = recordValue(sourceMapValue, "validated source_map");
  const knownBlocks = new Set(
    (Array.isArray(sourceMap.blocks) ? sourceMap.blocks : [])
      .map((value) => recordValue(value, "source-map block"))
      .map((block) => metadataId(block.block_id, "source-map block_id")),
  );
  if (selected.some((blockId) => !knownBlocks.has(blockId))) {
    throw new KernelValidationError(
      "materialize_extractive selected block ID is absent from the validated source-map receipt",
    );
  }
  const evidenceIds = materialize.evidence_ids;
  if (Array.isArray(evidenceIds)) {
    if (metadataIdList(evidenceIds, "materialize_extractive.evidence_ids").length !== selected.length) {
      throw new KernelValidationError("evidence_ids count must match selected block IDs");
    }
  } else {
    const mapping = recordValue(evidenceIds, "materialize_extractive.evidence_ids");
    assertExactMappingKeys(mapping, selected, "materialize_extractive.evidence_ids");
    for (const blockId of selected) metadataId(mapping[blockId], `evidence_ids.${blockId}`);
  }
  const requirements = materialize.requirement_ids;
  if (Array.isArray(requirements)) {
    requirements.forEach((id, index) => {
      metadataId(id, `requirement_ids[${index}]`);
    });
  } else {
    const mapping = recordValue(requirements, "materialize_extractive.requirement_ids");
    assertExactMappingKeys(mapping, selected, "materialize_extractive.requirement_ids");
    for (const blockId of selected) {
      const ids = mapping[blockId];
      if (!Array.isArray(ids)) throw new KernelValidationError(`requirement_ids.${blockId} must be an array`);
      ids.forEach((id, index) => metadataId(id, `requirement_ids.${blockId}[${index}]`));
    }
  }
}

function kernelRunOptions(
  signal: AbortSignal | undefined,
  timeoutMs: number | undefined,
): KernelRunOptions {
  return {
    ...(signal === undefined ? {} : { signal }),
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
  };
}

function activeToolModel(ctx: { readonly model?: unknown }): Readonly<{
  provider: string;
  model: string;
  locality: "local" | "remote";
}> {
  if (typeof ctx.model !== "object" || ctx.model === null) {
    throw new SourceSliceReadError(
      "SOURCE_MODEL_REQUIRED",
      "Authorized source reads require the actual calling model identity",
    );
  }
  const model = ctx.model as Record<string, unknown>;
  const provider = model.provider;
  const modelId = model.id ?? model.model;
  const baseUrl = model.baseUrl;
  if (
    typeof provider !== "string" ||
    typeof modelId !== "string" ||
    typeof baseUrl !== "string" ||
    !provider ||
    !modelId
  ) {
    throw new SourceSliceReadError(
      "SOURCE_MODEL_REQUIRED",
      "Authorized source reads require observable provider, model, and endpoint locality",
    );
  }
  let endpoint: URL;
  try {
    endpoint = new URL(baseUrl);
  } catch {
    throw new SourceSliceReadError(
      "SOURCE_MODEL_REQUIRED",
      "Calling model endpoint locality is not observable",
    );
  }
  if (!/^https?:$/.test(endpoint.protocol)) {
    throw new SourceSliceReadError(
      "SOURCE_MODEL_REQUIRED",
      "Calling model endpoint locality is not observable",
    );
  }
  const host = endpoint.hostname.toLowerCase();
  const locality = (
    host === "localhost" ||
    host === "::1" ||
    host.endsWith(".local") ||
    /^127\./.test(host) ||
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^172\.(?:1[6-9]|2\d|3[01])\./.test(host)
  ) ? "local" : "remote";
  return Object.freeze({ provider, model: modelId, locality });
}

async function verifyCallingSessionStorage(
  ctx: ExtensionContext,
  authorization: Readonly<{ sessionJsonlPath: string }>,
): Promise<void> {
  const callingSession = ctx.sessionManager.getSessionFile();
  if (!callingSession) {
    throw new SourceSliceReadError(
      "SESSION_STORAGE_INSECURE",
      "Calling OMP session JSONL is unavailable for privacy verification",
    );
  }
  const authorizedRoot = resolve(dirname(authorization.sessionJsonlPath));
  const callingPath = resolve(callingSession);
  const relativePath = relative(authorizedRoot, callingPath);
  if (
    (isAbsolute(relativePath) || relativePath === ".." || relativePath.startsWith(`..${sep}`)) &&
    callingPath !== resolve(authorization.sessionJsonlPath)
  ) {
    throw new SourceSliceReadError(
      "SESSION_STORAGE_INSECURE",
      "Calling OMP session is outside the authorized private session root",
    );
  }
  const expectedUid = typeof process.getuid === "function" ? process.getuid() : undefined;
  const file = await lstat(callingPath).catch(() => undefined);
  if (
    !file ||
    !file.isFile() ||
    file.isSymbolicLink() ||
    (file.mode & 0o077) !== 0 ||
    (expectedUid !== undefined && file.uid !== expectedUid)
  ) {
    throw new SourceSliceReadError(
      "SESSION_STORAGE_INSECURE",
      "Calling OMP session JSONL is not a current-user-owned private regular file",
    );
  }
  let directory = dirname(callingPath);
  while (true) {
    const metadata = await lstat(directory).catch(() => undefined);
    if (
      !metadata ||
      !metadata.isDirectory() ||
      metadata.isSymbolicLink() ||
      (metadata.mode & 0o077) !== 0 ||
      (metadata.mode & 0o700) !== 0o700 ||
      (expectedUid !== undefined && metadata.uid !== expectedUid)
    ) {
      throw new SourceSliceReadError(
        "SESSION_STORAGE_INSECURE",
        "Calling OMP session directory chain is not current-user-owned and private",
      );
    }
    if (directory === authorizedRoot) break;
    const parent = dirname(directory);
    if (parent === directory) {
      throw new SourceSliceReadError(
        "SESSION_STORAGE_INSECURE",
        "Calling OMP session directory does not reach the authorized root",
      );
    }
    directory = parent;
  }
}

function safeLocalError(error: unknown): ResumeToolError {
  if (error instanceof KernelBridgeError) {
    const structured: StructuredKernelError = error.structured();
    return Object.freeze({
      code: structured.code,
      message: structured.message,
      retryable: structured.retryable,
      operation: structured.operation,
      ...(structured.exitCode === undefined ? {} : { exitCode: structured.exitCode }),
      ...(structured.kernelType === undefined ? {} : { kernelType: structured.kernelType }),
    });
  }
  if (
    error instanceof ManifestContractError ||
    error instanceof SourceSliceReadError ||
    error instanceof SourcePolicyStateError ||
    error instanceof ApprovalStateError ||
    error instanceof ConfirmationBoundaryError
  ) {
    return Object.freeze({ code: error.code, message: error.message, retryable: false });
  }
  if (error instanceof KernelValidationError) {
    return Object.freeze({
      code: error.code,
      message: "Approval validation rejected the supplied evidence, reviews, confirmations, or claim lock",
      retryable: false,
    });
  }
  if (error instanceof SchemaValidationError) {
    return Object.freeze({
      code: error.code,
      message: "Approval payload failed authoritative schema validation",
      retryable: false,
    });
  }
  if (error instanceof SourceIdentityError) {
    return Object.freeze({
      code: error.code,
      message: "Approval source hash, span, and exact-quote revalidation failed",
      retryable: false,
    });
  }
  return Object.freeze({
    code: "PLUGIN_TOOL_FAILED",
    message: "Resume Plugin tool failed locally without persisting private exception text; verify the requested metadata and local prerequisites",
    retryable: false,
  });
}

async function executeWithEnvelope(
  tool: ResumeToolName,
  runId: string,
  runtime: ResumePluginRuntime,
  operation: () => Promise<unknown>,
) {
  let envelope: ResumeToolEnvelope;
  try {
    const data = normalizeJson(await operation());
    runtime.recordToolSuccess(tool, runId);
    envelope = Object.freeze({ ok: true, tool, runId, data });
  } catch (error) {
    envelope = Object.freeze({ ok: false, tool, runId, error: safeLocalError(error) });
  }
  return {
    content: [{ type: "text" as const, text: JSON.stringify(envelope) }],
    details: envelope,
    ...(envelope.ok ? {} : { isError: true }),
  };
}

export function registerResumeTools(
  pi: ExtensionAPI,
  runtime: ResumePluginRuntime,
  options: RegisterResumeToolsOptions = {},
): void {
  const z = pi.zod;
  const bridge = options.bridge ?? new PythonKernelBridge();
  const runId = z.string().min(1).max(128).optional().describe("Run ID from /resume-init; defaults to the active run");
  const timeoutMs = z.number().int().min(100).max(600_000).optional().describe("Local Python kernel timeout in milliseconds");
  const jsonObject = z.record(z.string(), z.unknown()).describe("Strict JSON object consumed by the deterministic resume kernels");

  pi.registerTool({
    name: "resume_discover_structure",
    label: "Discover Resume Source Structure",
    description: "Build a metadata-only, fence-aware source map with paths, hashes, spans, headings, ancestry, and policy metadata. This tool does not expose source bodies or orchestrate agents.",
    parameters: z.object({
      runId,
      sourceRoot: z.string().min(1).describe("Read-only career source root"),
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_discover_structure", selectedRunId, runtime, async () => {
        const result = await bridge.run(
          { operation: "discover-source-structure", sourceRoot: params.sourceRoot, input: {} },
          kernelRunOptions(signal, params.timeoutMs),
        );
        const sourceMap = validatedSourceMapResult(result);
        return {
          operation: "discover-source-structure",
          source_map: sourceMap,
          document_count: Array.isArray(sourceMap.documents) ? sourceMap.documents.length : 0,
          section_count: Array.isArray(sourceMap.sections) ? sourceMap.sections.length : 0,
          block_count: Array.isArray(sourceMap.blocks) ? sourceMap.blocks.length : 0,
        };
      });
    },
  });

  pi.registerTool({
    name: "resume_read_source_slice",
    label: "Read Authorized Resume Source Slice",
    description: "Read one exact line-bounded source slice only after explicit per-run reviewed-semantic authorization and deterministic contact, credential, F6/P3, scope, path, and size prefiltering. Metadata-only runs always fail closed.",
    parameters: z.object({
      runId: z.string().min(1).max(128).describe("Explicit reviewed-semantic run ID"),
      consumer: z.enum(["main", "source-mapper", "role-analyst", "requirement-reviewer", "evidence-reviewer", "contribution-reviewer", "privacy-reviewer", "resume-advisor"]),
      repositoryRoot: z.string().min(1).describe("Authorized read-only source root"),
      path: z.string().min(1).describe("Exact path recorded in the authorization minimum-slice list"),
      startLine: z.number().int().positive(),
      endLine: z.number().int().positive(),
      category: z.string().min(1).describe("Authorized disclosure category"),
      purpose: z.string().min(1).max(240).describe("Exact authorized review purpose for this consumer"),
      sourceMapDigest: z.string().regex(/^sha256:[a-f0-9]{64}$/).describe("Digest returned by same-run resume_validate_source_map"),
      maxBytes: z.number().int().positive().max(65_536).optional(),
      requestId: z.string().min(1).max(128).optional(),
    }).strict(),
    approval: "read",
    strict: true,
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      return executeWithEnvelope("resume_read_source_slice", params.runId, runtime, async () => {
        const state = runtime.privacyState(params.runId);
        if (state.mode === "metadata-only") {
          throw new SourceSliceReadError(
            "metadata-only",
            "Metadata-only mode never discloses source bodies",
          );
        }
        const authorization = state.authorization;
        if (!authorization) {
          throw new SourceSliceReadError(
            "missing-authorization",
            "Reviewed-semantic authorization is required before any source read",
          );
        }
        const model = activeToolModel(ctx);
        const policyPath = relativeSourcePath(params.repositoryRoot, params.path);
        const policy = runtime.sourcePolicyForSlice(
          policyPath,
          params.startLine,
          params.endLine,
          params.sourceMapDigest,
          params.runId,
        );
        await verifyCallingSessionStorage(ctx, authorization);
        const result = await readPrefilteredSourceSlice({
          state,
          consumer: params.consumer,
          repositoryRoot: params.repositoryRoot,
          path: params.path,
          startLine: params.startLine,
          endLine: params.endLine,
          category: params.category,
          authorizationId: authorization.authorizationId,
          provider: model.provider,
          model: model.model,
          locality: model.locality,
          purpose: params.purpose,
          effectivePolicy: policy.effectivePolicy,
          ancestorPolicies: policy.ancestorPolicies,
          expectedSourceHash: policy.expectedSourceHash,
          blockedByPolicy: policy.blockedByPolicy,
          ...(params.maxBytes === undefined ? {} : { maxBytes: params.maxBytes }),
          ...(params.requestId === undefined ? {} : { requestId: params.requestId }),
        });
        if (!result.ok) {
          throw new SourceSliceReadError(result.code, result.reason);
        }
        return result;
      });
    },
  });

  pi.registerTool({
    name: "resume_validate_source_map",
    label: "Validate Resume Source Map",
    description: "Re-open the source and deterministically validate source identity, hashes, spans, quotes, and policy metadata. Agent output cannot override this validator.",
    parameters: z.object({
      runId,
      sourceRoot: z.string().min(1),
      sourceMap: jsonObject,
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_validate_source_map", selectedRunId, runtime, async () => {
        const result = await bridge.run(
          {
            operation: "validate-source-map",
            sourceRoot: params.sourceRoot,
            input: requireJsonObject(params.sourceMap),
          },
          kernelRunOptions(signal, params.timeoutMs),
        );
        const validatedSourceMap = validatedSourceMapResult(result);
        const summary = runtime.recordSourcePolicyIndex(
          sourcePolicyIndex(selectedRunId, result),
          selectedRunId,
        );
        runtime.recordValidatedSourceMap(
          summary.digest,
          validatedSourceMap,
          selectedRunId,
        );
        pi.appendEntry("china-targeted-resume/source-policy", {
          runId: selectedRunId,
          ...summary,
        });
        return {
          operation: "validate-source-map",
          source_map_receipt: {
            run_id: selectedRunId,
            digest: summary.digest,
            entry_count: summary.entryCount,
          },
        };
      });
    },
  });

  pi.registerTool({
    name: "resume_validate_role_ir",
    label: "Validate Resume Role IR",
    description: "Deterministically validate normalized role IR, exact requirement quotes/spans, freshness, and company/role/roadmap separation.",
    parameters: z.object({
      runId,
      sourceRoot: z.string().min(1),
      payload: jsonObject.describe("Bundle containing source_map and normalized_role_input"),
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_validate_role_ir", selectedRunId, runtime, async () => bridge.run(
        {
          operation: "validate-role-input",
          sourceRoot: params.sourceRoot,
          input: requireJsonObject(params.payload),
        },
        kernelRunOptions(signal, params.timeoutMs),
      ));
    },
  });

  pi.registerTool({
    name: "resume_validate_evidence_ir",
    label: "Validate Resume Evidence IR",
    description: "Materialize selected extractive block IDs privately in metadata-only mode, or validate explicitly authorized reviewed-semantic evidence; returns receipt metadata only.",
    parameters: z.object({
      runId,
      sourceRoot: z.string().min(1),
      sourceMapDigest: z.string().regex(/^sha256:[a-f0-9]{64}$/).describe("Same-run validated source-map receipt digest"),
      payload: jsonObject.describe("Metadata-only materialize_extractive selector IDs, or an explicitly authorized reviewed-semantic canonical evidence IR"),
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_validate_evidence_ir", selectedRunId, runtime, async () => {
        const supplied = requireJsonObject(params.payload);
        const privacy = runtime.privacyState(selectedRunId);
        if (Object.hasOwn(supplied, "source_map") || Object.hasOwn(supplied, "source_map_ir")) {
          throw new KernelValidationError(
            "Caller-supplied source_map is forbidden; use the validated source-map receipt",
          );
        }
        const sourceMap = runtime.validatedSourceMap(params.sourceMapDigest, selectedRunId);
        if (privacy.mode === "metadata-only") {
          assertMetadataOnlyEvidenceRequest(supplied, sourceMap);
        }
        const kernelInput = requireJsonObject({
          source_map: sourceMap,
          ...supplied,
        });
        const result = await bridge.run(
          {
            operation: "validate-evidence-input",
            sourceRoot: params.sourceRoot,
            input: kernelInput,
          },
          kernelRunOptions(signal, params.timeoutMs),
        );
        const bundle = validatedEvidenceBundle(result, kernelInput);
        const receipt = evidenceValidationReceipt(selectedRunId, bundle);
        pi.appendEntry("china-targeted-resume/evidence-validation", receipt);
        runtime.recordEvidenceValidation(receipt, selectedRunId);
        runtime.recordEvidenceBundle(receipt, bundle, selectedRunId);
        return {
          operation: "validate-evidence-input",
          mode: privacy.mode,
          evidence_receipt: receipt,
        };
      });
    },
  });
  pi.registerTool({
    name: "resume_lock_approved_claims",
    label: "Lock Approved Resume Claims",
    description: "Apply deterministic hard-disagreement rules to one same-run validated evidence receipt. Required confirmations are collected interactively and caller booleans are forbidden.",
    parameters: z.object({
      runId,
      sourceRoot: z.string().min(1),
      evidenceReceiptDigest: z.string().regex(/^sha256:[a-f0-9]{64}$/),
      payload: jsonObject.describe("Independent review_decisions, approved_safe_claims, and explicit output_mode; no evidence bodies or confirmation booleans"),
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_lock_approved_claims", selectedRunId, runtime, async () => {
        signal?.throwIfAborted();
        const payload = requireJsonObject(params.payload);
        rejectCallerEvidence(payload);
        rejectCallerConfirmations(payload);
        const evidenceReceipt = runtime.evidenceReceipt(
          params.evidenceReceiptDigest,
          selectedRunId,
        );
        const privacy = runtime.privacyState(selectedRunId);
        if (
          evidenceReceipt.requiresReviewedSemantic &&
          privacy.mode !== "reviewed-semantic"
        ) {
          throw new KernelValidationError(
            "Evidence receipt requires explicit reviewed-semantic authorization before claim locking",
          );
        }
        const bundle = runtime.evidenceBundle(
          params.evidenceReceiptDigest,
          selectedRunId,
        );
        const evidence = normalizeEvidenceInput(bundle.evidenceInput);
        const reviews = approvalReviews(payload, {
          mode: privacy.mode,
          ...(privacy.authorization === undefined
            ? {}
            : { authorizationId: privacy.authorization.authorizationId }),
        });
        const claims = approvedSafeClaims(payload);
        const outputMode = approvalOutputMode(payload);
        runtime.assertEvidenceValidation(evidenceReceipt, selectedRunId);
        const revalidatedEvidence = await revalidateApprovalSources(
          params.sourceRoot,
          evidence,
        );
        signal?.throwIfAborted();
        const confirmations = await collectConfirmationReceipts(
          pi,
          ctx,
          runtime,
          selectedRunId,
          revalidatedEvidence,
          reviews,
          claims,
          outputMode,
        );
        const options = approvalOptions(payload, confirmations, selectedRunId);
        const result = approveAndLockClaims(
          selectedRunId,
          revalidatedEvidence,
          reviews,
          options,
        );
        const authorizationId = privacy.authorization?.authorizationId;
        const receipt = approvalReceipt(result.approval_lock, authorizationId);
        pi.appendEntry("china-targeted-resume/approval-lock", receipt);
        runtime.recordApprovalReceipt(receipt, selectedRunId);
        runtime.recordApprovalBundle(receipt, {
          approvedClaims: result.approved_claims,
          approvalLock: result.approval_lock,
          reviews,
          approvedSafeClaims: claims ?? {},
          outputMode,
          evidenceReceiptDigest: params.evidenceReceiptDigest,
          ...(authorizationId === undefined ? {} : { authorizationId }),
          confirmationReceipts: confirmations,
        }, selectedRunId);
        return {
          backend: "typescript",
          approval_receipt: receipt,
          claim_count: receipt.claimIds.length,
          evidence_receipt_digest: params.evidenceReceiptDigest,
        };
      });
    },
  });

  pi.registerTool({
    name: "resume_compose_variants",
    label: "Compose Resume Variants",
    description: "Verify one same-run evidence receipt, interactive confirmation receipts, and exact approval lock before composing private resume variants.",
    parameters: z.object({
      runId,
      evidenceReceiptDigest: z.string().regex(/^sha256:[a-f0-9]{64}$/),
      approvalReceiptDigest: z.string().regex(/^sha256:[a-f0-9]{64}$/),
      sourceRoot: z.string().min(1).optional(),
      outputRoot: z.string().min(1).optional(),
      includeExtendedProfile: z.boolean().optional(),
      payload: jsonObject.describe("Generation-only metadata with output_mode, placements, candidate profile claim IDs, and request; no evidence, review, approval, or confirmation bodies"),
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_compose_variants", selectedRunId, runtime, async () => {
        const approvalReceiptValue = runtime.approvalReceipt(
          params.approvalReceiptDigest,
          selectedRunId,
        );
        signal?.throwIfAborted();
        const payload = requireJsonObject(params.payload);
        rejectCallerEvidence(payload);
        rejectCallerConfirmations(payload);
        rejectCallerApproval(payload);
        const approvalBundle = runtime.approvalBundle(
          params.approvalReceiptDigest,
          selectedRunId,
        );
        if (approvalBundle.evidenceReceiptDigest !== params.evidenceReceiptDigest) {
          throw new ApprovalStateError(
            "APPROVAL_LOCK_MISMATCH",
            "Compose evidence receipt does not match the locked approval bundle",
          );
        }
        const evidenceReceipt = runtime.evidenceReceipt(
          params.evidenceReceiptDigest,
          selectedRunId,
        );
        const bundle = runtime.evidenceBundle(
          params.evidenceReceiptDigest,
          selectedRunId,
        );
        runtime.assertEvidenceValidation(evidenceReceipt, selectedRunId);
        const outputMode = approvalOutputMode(payload);
        if (outputMode !== approvalBundle.outputMode) {
          throw new ApprovalStateError(
            "APPROVAL_LOCK_MISMATCH",
            "Compose output mode does not match the locked approval bundle",
          );
        }
        const evidence = normalizeEvidenceInput(bundle.evidenceInput);
        const reviews = approvalBundle.reviews;
        const claims = approvalBundle.approvedSafeClaims;
        const requests = deriveConfirmationRequests(
          selectedRunId,
          evidence,
          reviews,
          { approvedSafeClaims: claims, outputMode },
        );
        const confirmations = verifiedRuntimeConfirmations(
          runtime,
          selectedRunId,
          requests,
        );
        const options: ApproveClaimsOptions = {
          approvedSafeClaims: claims,
          confirmationReceipts: confirmations,
          runId: selectedRunId,
          outputMode,
        };
        const verified = verifyApprovalLock(
          selectedRunId,
          approvalBundle.approvalLock,
          evidence,
          reviews,
          approvalBundle.approvedClaims,
          options,
        );
        runtime.assertApprovalReceipt(
          approvalReceipt(verified, approvalBundle.authorizationId),
          selectedRunId,
        );
        runtime.assertApprovalReceipt(approvalReceiptValue, selectedRunId);
        const pythonConfirmations = Object.fromEntries(
          confirmations.map((receipt) => [receipt.evidence_id, true]),
        );
        const kernelPayload = requireJsonObject({
          ...payload,
          source_map: bundle.sourceMap,
          evidence_input: bundle.evidenceInput,
          review_decisions: reviews,
          approved_safe_claims: claims,
          approved_claims: approvalBundle.approvedClaims,
          approval_lock: approvalBundle.approvalLock,
          user_confirmations: pythonConfirmations,
        });
        signal?.throwIfAborted();
        return bridge.run(
          {
            operation: "generate-from-ir",
            input: kernelPayload,
            ...(params.sourceRoot === undefined ? {} : { sourceRoot: params.sourceRoot }),
            ...(params.outputRoot === undefined ? {} : { outputRoot: params.outputRoot }),
            ...(params.includeExtendedProfile === undefined ? {} : { includeExtendedProfile: params.includeExtendedProfile }),
          },
          kernelRunOptions(signal, params.timeoutMs),
        );
      });
    },
  });

  pi.registerTool({
    name: "resume_render_variants",
    label: "Render Resume Variants",
    description: "Re-render every resume document listed in a private resume-variants.json manifest using the bundled Python renderer. Artifact names are manifest-bounded and traversal-safe.",
    parameters: z.object({
      runId,
      manifestPath: z.string().min(1),
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_render_variants", selectedRunId, runtime, async () => {
        const manifest = await readVariantManifest(params.manifestPath);
        const documents = await resolveVariantArtifacts(params.manifestPath, manifest, "document");
        const pdfs = await resolveVariantArtifacts(params.manifestPath, manifest, "pdf");
        const pdfByVariant = new Map(pdfs.map((item) => [item.variant, item.path]));
        const results: JsonObject[] = [];
        for (const document of documents) {
          const outputPath = pdfByVariant.get(document.variant);
          if (!outputPath) throw new ManifestContractError("MISSING_ARTIFACT", `Variant ${document.variant} does not list a PDF artifact`);
          results.push(await bridge.run(
            { operation: "render", documentPath: document.path, outputPath, input: {} },
            kernelRunOptions(signal, params.timeoutMs),
          ));
        }
        const summary = summarizeVariantManifest(manifest);
        runtime.recordManifest(summary, selectedRunId);
        return { manifest: normalizeJson(summary), results };
      });
    },
  });

  pi.registerTool({
    name: "resume_inspect_variants",
    label: "Inspect Resume Variants",
    description: "Inspect every PDF listed in private resume-variants.json and return typed real-PDF checks. A subset cannot be supplied, so a manifest-listed variant cannot be silently skipped.",
    parameters: z.object({
      runId,
      manifestPath: z.string().min(1),
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_inspect_variants", selectedRunId, runtime, async () => {
        const manifest = await readVariantManifest(params.manifestPath);
        const pdfs = await resolveVariantArtifacts(params.manifestPath, manifest, "pdf");
        const documents = await resolveVariantArtifacts(params.manifestPath, manifest, "document");
        const documentByVariant = new Map(documents.map((item) => [item.variant, item.path]));
        const targetPages = new Map(manifest.variants.map((variant) => [variant.variant, variant.targetPages]));
        const results: JsonObject[] = [];
        for (const pdf of pdfs) {
          const documentPath = documentByVariant.get(pdf.variant);
          if (!documentPath) {
            throw new ManifestContractError(
              "MISSING_ARTIFACT",
              `Variant ${pdf.variant} does not list a contained ResumeDocument artifact`,
            );
          }
          const inspection = await bridge.run(
            {
              operation: "inspect-pdf",
              pdfPath: pdf.path,
              documentPath,
              maxPages: targetPages.get(pdf.variant) ?? 2,
              input: {},
            },
            kernelRunOptions(signal, params.timeoutMs),
          );
          results.push({ variant: pdf.variant, inspection });
        }
        const summary = summarizeVariantManifest(manifest);
        runtime.recordManifest(summary, selectedRunId);
        return { manifest: normalizeJson(summary), results };
      });
    },
  });

  pi.registerTool({
    name: "resume_write_growth_roadmap",
    label: "Write Validated Growth Roadmap",
    description: "Validate a private roadmap plan against the exact roadmap-handoff bytes and write non-overwriting 0700/0600 JSON, Markdown, and validation artifacts through the bundled Python backend.",
    parameters: z.object({
      runId,
      sourceRoot: z.string().min(1).describe("Read-only career source root used for output-boundary validation"),
      handoffPath: z.string().min(1).describe("Private roadmap-handoff.json path"),
      planPath: z.string().min(1).describe("Private growth-roadmap plan JSON path"),
      outputRoot: z.string().min(1).describe("Private output root outside the source root"),
      timeoutMs,
    }).strict(),
    approval: "exec",
    strict: true,
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const selectedRunId = params.runId ?? runtime.activeRunId;
      return executeWithEnvelope("resume_write_growth_roadmap", selectedRunId, runtime, async () => {
        return bridge.run(
          {
            operation: "write-growth-roadmap",
            sourceRoot: params.sourceRoot,
            handoffPath: params.handoffPath,
            planPath: params.planPath,
            outputRoot: params.outputRoot,
            input: {},
          },
          kernelRunOptions(signal, params.timeoutMs),
        );
      });
    },
  });
}
