import { describe, expect, test } from "bun:test";
import { join } from "node:path";
import {
  approveClaims,
  deriveConfirmationRequests,
  KernelValidationError,
  lockApprovedClaims,
  type ApprovalBasis,
  type DisclosureAudience,
  type DisclosureDecision,
} from "../../src/kernel/approval.ts";
import {
  evaluatePolicy,
  parsePolicyMarkers,
  PolicyValidationError,
  type EffectivePolicyInput,
} from "../../src/kernel/policy.ts";
import { buildProvenance, checkProvenanceClosure } from "../../src/kernel/provenance.ts";
import { canonicalJsonText } from "../../src/kernel/secure-io.ts";
import {
  validateSchemaDocument,
  type JsonObject,
} from "../../src/kernel/schema.ts";
import {
  revalidateExactQuote,
  sha256Bytes,
  sourceSpanFromBytes,
  type SourceHash,
} from "../../src/kernel/source-identity.ts";

type SourceFixtures = JsonObject & {
  readonly record: string;
  readonly sha256: SourceHash;
  readonly utf8_spans: readonly JsonObject[];
};
type GoldenManifest = JsonObject & {
  readonly source_fixtures: SourceFixtures;
  readonly schema_cases: string;
  readonly kernel_cases_executable: string;
  readonly schema_normalized: string;
  readonly approval_cases_executable: string;
  readonly verification_matrix: readonly JsonObject[];
  readonly backend_matrix: JsonObject;
  readonly policy_cases: readonly JsonObject[];
  readonly approval_cases: readonly JsonObject[];
  readonly provenance_cases: readonly JsonObject[];
  readonly variants: JsonObject;
  readonly audit_cases: readonly JsonObject[];
  readonly html_cases: readonly JsonObject[];
  readonly pdf_cases: readonly JsonObject[];
  readonly io_cases: readonly JsonObject[];
};
type MutablePolicyInput = {
  -readonly [Key in keyof EffectivePolicyInput]: EffectivePolicyInput[Key];
};
type SchemaCases = { readonly cases: readonly JsonObject[] };
type SchemaNormalized = {
  readonly fixture_version: 1;
  readonly cases: Readonly<Record<string, JsonObject>>;
};
type KernelCases = {
  readonly policy_cases: readonly JsonObject[];
  readonly closure_cases: readonly JsonObject[];
  readonly approval_cases: readonly JsonObject[];
  readonly lock_cases: readonly JsonObject[];
  readonly provenance_cases: readonly JsonObject[];
  readonly invalid_policy_cases: readonly JsonObject[];
};
type ApprovalCases = { readonly cases: readonly JsonObject[] };

const GOLDEN_ROOT = join(import.meta.dir, "../golden");
const manifest = (await Bun.file(join(GOLDEN_ROOT, "manifest.json")).json()) as GoldenManifest;
const schemaCasesDocument = (await Bun.file(join(GOLDEN_ROOT, manifest.schema_cases)).json()) as SchemaCases;
const schemaNormalizedDocument = (
  await Bun.file(join(GOLDEN_ROOT, manifest.schema_normalized)).json()
) as SchemaNormalized;
const approvalCasesDocument = (
  await Bun.file(join(GOLDEN_ROOT, manifest.approval_cases_executable)).json()
) as ApprovalCases;
const kernelCasesDocument = (
  await Bun.file(join(GOLDEN_ROOT, manifest.kernel_cases_executable)).json()
) as KernelCases;
function collectStableIds(value: unknown, result = new Set<string>()): Set<string> {
  if (Array.isArray(value)) {
    for (const item of value) collectStableIds(item, result);
    return result;
  }
  if (!isObject(value)) return result;
  for (const [key, item] of Object.entries(value)) {
    if (key.endsWith("_id") && typeof item === "string") result.add(item);
    if (key.endsWith("_ids") && Array.isArray(item)) {
      for (const id of item) if (typeof id === "string") result.add(id);
    }
    collectStableIds(item, result);
  }
  return result;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isApprovalBasis(value: unknown): value is ApprovalBasis {
  return value === "mechanical"
    || value === "independent_review"
    || value === "user_confirmed";
}

function isDisclosureDecision(value: unknown): value is DisclosureDecision {
  return value === "allowed"
    || value === "denied"
    || value === "needs_confirmation";
}

function isDisclosureAudienceOrNull(
  value: unknown,
): value is DisclosureAudience | null {
  return value === null
    || value === "recruiter"
    || value === "hiring_team"
    || value === "public"
    || value === "internal";
}
function stringRecord(value: unknown): Record<string, string> {
  if (!isObject(value)) return {};
  const result: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry !== "string") throw new Error(`expected string value for ${key}`);
    result[key] = entry;
  }
  return result;
}

function booleanRecord(value: unknown): Record<string, boolean> {
  if (!isObject(value)) return {};
  const result: Record<string, boolean> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry !== "boolean") throw new Error(`expected boolean value for ${key}`);
    result[key] = entry;
  }
  return result;
}
function isStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isFactPolicy(value: unknown): value is NonNullable<EffectivePolicyInput["document_fact_policy"]> {
  return value === "F1" || value === "F2" || value === "F3" || value === "F4" || value === "F5" || value === "F6";
}

function isDisclosurePolicy(value: unknown): value is NonNullable<EffectivePolicyInput["document_disclosure_policy"]> {
  return value === "P0" || value === "P1" || value === "P2" || value === "P3";
}

function isOutputMode(value: unknown): value is NonNullable<EffectivePolicyInput["output_mode"]> {
  return value === "targeted_application" || value === "public_portfolio" || value === "master_resume";
}

function isFactPolicyArray(value: unknown): value is readonly (NonNullable<EffectivePolicyInput["document_fact_policy"]> | null)[] {
  return Array.isArray(value) && value.every((item) => isFactPolicy(item) || item === null);
}

function isDisclosurePolicyArray(
  value: unknown,
): value is readonly (NonNullable<EffectivePolicyInput["document_disclosure_policy"]> | null)[] {
  return Array.isArray(value) && value.every((item) => isDisclosurePolicy(item) || item === null);
}

function effectivePolicyInput(value: JsonObject): EffectivePolicyInput {
  const result: MutablePolicyInput = {};
  for (const key of ["document_fact_policy", "ancestor_fact_policy", "local_fact_policy"] as const) {
    if (isFactPolicy(value[key])) result[key] = value[key];
  }
  for (const key of ["document_disclosure_policy", "ancestor_disclosure_policy", "local_disclosure_policy"] as const) {
    if (isDisclosurePolicy(value[key])) result[key] = value[key];
  }
  if (isFactPolicyArray(value.ancestor_fact_policies)) result.ancestor_fact_policies = value.ancestor_fact_policies;
  if (isDisclosurePolicyArray(value.ancestor_disclosure_policies)) {
    result.ancestor_disclosure_policies = value.ancestor_disclosure_policies;
  }
  if (isObject(value.structural_flags)) result.structural_flags = value.structural_flags;
  if (isOutputMode(value.output_mode)) result.output_mode = value.output_mode;
  if (typeof value.p2_confirmed === "boolean") result.p2_confirmed = value.p2_confirmed;
  return result;
}
function mutableRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isObject(value)) throw new Error(`malformed ${label}`);
  return Object.fromEntries(Object.entries(value));
}

function resolveDerivedApproval(derived: JsonObject): {
  readonly evidence: Record<string, unknown>;
  readonly reviews: unknown;
  readonly options: Record<string, unknown>;
} {
  const baseCaseId = derived.base_case;
  if (typeof baseCaseId !== "string") throw new Error("missing approval base case");
  const base = approvalCasesDocument.cases.find((item) => isObject(item) && item.case_id === baseCaseId);
  if (!isObject(base)) throw new Error(`unknown approval base case ${baseCaseId}`);
  const evidence = mutableRecord(JSON.parse(JSON.stringify(base.evidence)), "evidence");
  const candidates = evidence.candidates;
  if (!Array.isArray(candidates) || candidates.length === 0) throw new Error("missing base evidence candidate");
  const candidate = mutableRecord(candidates[0], "candidate");
  const overrides = mutableRecord(derived.candidate_overrides, "candidate overrides");
  const source = mutableRecord(candidate.source, "source");
  const flags = mutableRecord(source.structural_flags, "structural flags");
  if (typeof overrides.input_id !== "string" || typeof overrides.evidence_id !== "string") {
    throw new Error("malformed candidate identifiers");
  }
  evidence.input_id = overrides.input_id;
  candidate.evidence_id = overrides.evidence_id;
  if (typeof overrides.owner === "string") candidate.owner = overrides.owner;
  if (typeof overrides.claim_mode === "string") candidate.claim_mode = overrides.claim_mode;
  if (isObject(overrides.unresolved_questions) || Array.isArray(overrides.unresolved_questions)) {
    candidate.unresolved_questions = overrides.unresolved_questions;
  }
  if (Array.isArray(derived.evidence_unresolved_questions)) {
    evidence.unresolved_questions = derived.evidence_unresolved_questions;
  }
  flags.effective_fact_policy = overrides.effective_fact_policy;
  flags.effective_disclosure_policy = overrides.effective_disclosure_policy;
  source.structural_flags = flags;
  candidate.source = source;
  evidence.candidates = [candidate];
  const reviews = derived.reviews;
  const options = mutableRecord(derived.options, "approval options");
  return { evidence, reviews, options };
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (!isObject(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
}

function sameCanonical(left: unknown, right: unknown): boolean {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

function expectSchemaOutcome(item: JsonObject): void {
  const caseId = item.case_id;
  const schema = item.schema;
  const input = item.input;
  if (typeof caseId !== "string" || typeof schema !== "string" || !isObject(input)) {
    throw new Error("malformed schema fixture");
  }
  const accepted = item.accepted === true;
  const validationLayer = item.validation_layer;
  if (!accepted && validationLayer === "canonical") return;
  if (accepted) {
    const expected = schemaNormalizedDocument.cases[caseId];
    if (!isObject(expected)) throw new Error(`missing frozen normalized schema fixture for ${caseId}`);
    const normalized = validateSchemaDocument(input, schema);
    expect(normalized).toEqual(expected);
    const expectedIds = isObject(item.expected) ? item.expected.stable_ids : undefined;
    if (Array.isArray(expectedIds)) {
      const actualIds = collectStableIds(normalized);
      for (const id of expectedIds) {
        if (typeof id === "string") expect(actualIds.has(id)).toBe(true);
      }
    }
    const expectedHashes = isObject(item.expected) ? item.expected.source_hashes : undefined;
    if (Array.isArray(expectedHashes)) {
      const serialized = JSON.stringify(normalized);
      for (const hash of expectedHashes) {
        if (typeof hash === "string") expect(serialized.includes(hash)).toBe(true);
      }
    }
    if (schema === "approved-claims" && Array.isArray(input.claims)) {
      const finalClaims: Record<string, string> = {};
      for (const claim of input.claims) {
        if (!isObject(claim) || typeof claim.claim_id !== "string" || typeof claim.approved_safe_claim !== "string") {
          throw new Error("malformed approved claim fixture");
        }
        finalClaims[claim.claim_id] = claim.approved_safe_claim;
      }
      const locked = lockApprovedClaims(input, finalClaims);
      expect(sameCanonical(locked, normalized)).toBe(true);
      const firstClaimId = Object.keys(finalClaims)[0];
      if (firstClaimId === undefined) throw new Error("empty approved claim fixture");
      expect(() => lockApprovedClaims(input, {
        ...finalClaims,
        [firstClaimId]: `${finalClaims[firstClaimId]} changed`,
      })).toThrow();
    }
    return;
  }
  expect(() => validateSchemaDocument(input, schema)).toThrow();
}

describe("Phase 3 language-neutral golden fixtures", () => {
  test("validates every schema case against frozen complete normalized outputs", () => {
    const acceptedIds = schemaCasesDocument.cases.flatMap((item) => (
      item.accepted === true && typeof item.case_id === "string" ? [item.case_id] : []
    )).sort();
    expect(Object.keys(schemaNormalizedDocument.cases).sort()).toEqual(acceptedIds);
    for (const item of schemaCasesDocument.cases) expectSchemaOutcome(item);
  });
  test("executes shared P2 extractive approval cases", () => {
    for (const item of approvalCasesDocument.cases) {
      if (!isObject(item)) throw new Error("malformed approval case");
      const evidence = item.evidence;
      const reviews = item.reviews;
      const options = item.options;
      const expected = item.expected;
      if (!isObject(evidence) || !isObject(reviews) || !isObject(options) || !isObject(expected)) {
        throw new Error("malformed P2 approval case");
      }
      const approvedSafeClaims = stringRecord(options.approved_safe_claims);
      const runId = "run.golden";
      const outputMode = "targeted_application" as const;
      const confirmationMap = booleanRecord(options.user_confirmations);
      const confirmationRequests = deriveConfirmationRequests(
        runId,
        evidence,
        reviews,
        { approvedSafeClaims, outputMode },
      );
      const approvalOptions = confirmationMap[Object.keys(confirmationMap)[0] ?? ""] === true
        ? (() => {
          const request = confirmationRequests[0];
          if (request === undefined) throw new Error("missing P2 confirmation request");
          return {
            approvedSafeClaims,
            runId,
            outputMode,
            confirmationReceipts: [{
              ...request,
              confirmed: true as const,
              confirmed_at: "2026-08-21T00:00:00.000Z",
              confirmed_by: "interactive_user" as const,
              nonce: "nonce.golden",
            }],
          };
        })()
        : { approvedSafeClaims, runId, outputMode, confirmationReceipts: [] };
      if (expected.accepted === true) {
        const claimId = expected.claim_id;
        const approvalBasis = expected.approval_basis;
        const reviewerDecisionIds = expected.reviewer_decision_ids;
        const approvedSafeClaim = expected.approved_safe_claim;
        const disclosureDecision = expected.disclosure_decision;
        const disclosureAudience = expected.disclosure_audience;
        const disclosurePurpose = expected.disclosure_purpose;
        if (
          typeof claimId !== "string"
          || !isApprovalBasis(approvalBasis)
          || !Array.isArray(reviewerDecisionIds)
          || !reviewerDecisionIds.every((value) => typeof value === "string")
          || typeof approvedSafeClaim !== "string"
          || !isDisclosureDecision(disclosureDecision)
          || !isDisclosureAudienceOrNull(disclosureAudience)
          || (disclosurePurpose !== null && typeof disclosurePurpose !== "string")
        ) {
          throw new Error("malformed accepted P2 approval expectation");
        }
        const result = approveClaims(evidence, reviews, approvalOptions);
        const claim = result.claims[0];
        if (claim === undefined) throw new Error("P2 approval returned no claim");
        const expectedClaim = Object.fromEntries(Object.entries(expected).filter(([key]) => key !== "accepted"));
        expect(sameCanonical(claim, expectedClaim)).toBe(true);
        expect(claim.claim_id).toBe(claimId);
        expect(claim.approval_basis).toBe(approvalBasis);
        expect(claim.reviewer_decision_ids).toEqual(reviewerDecisionIds);
        expect(claim.approved_safe_claim).toBe(approvedSafeClaim);
        expect(claim.disclosure_decision).toBe(disclosureDecision);
        expect(claim.disclosure_audience).toBe(disclosureAudience);
        expect(claim.disclosure_purpose).toBe(disclosurePurpose);
      } else if (typeof expected.error_message === "string") {
        const expectedCode = expected.ts_error_code;
        if (typeof expectedCode !== "string") throw new Error("missing P2 stable error code");
        try {
          approveClaims(evidence, reviews, approvalOptions);
          throw new Error("P2 approval unexpectedly succeeded");
        } catch (error) {
          if (!(error instanceof KernelValidationError)) throw error;
          expect(error.message).toBe(expected.error_message);
          expect(error.code).toBe(expectedCode);
        }
      } else {
        const errorText = expected.error_contains;
        if (typeof errorText !== "string") throw new Error("missing P2 rejection text");
        expect(() => approveClaims(evidence, reviews, approvalOptions)).toThrow(errorText);
      }
    }
  });
  test("executes shared policy, approval, lock, and provenance cases", () => {
    for (const item of kernelCasesDocument.policy_cases) {
      if (!isObject(item) || !isObject(item.typescript_input) || !isObject(item.expected_typescript)) {
        throw new Error("malformed policy parity case");
      }
      expect(sameCanonical(evaluatePolicy(effectivePolicyInput(item.typescript_input)), item.expected_typescript)).toBe(true);
    }
    for (const item of kernelCasesDocument.invalid_policy_cases) {
      if (!isObject(item) || !isObject(item.defaults) || typeof item.text !== "string" || typeof item.expected_error !== "string") {
        throw new Error("malformed invalid policy case");
      }
      try {
        Reflect.apply(parsePolicyMarkers, null, [item.text, item.defaults]);
        throw new Error("invalid policy unexpectedly accepted");
      } catch (error) {
        if (!(error instanceof PolicyValidationError)) throw error;
        expect(error.message).toBe(item.expected_error);
      }
    }

    for (const item of kernelCasesDocument.approval_cases) {
      if (!isObject(item) || !isObject(item.expected)) throw new Error("malformed approval parity case");
      const resolved = resolveDerivedApproval(item);
      const expected = item.expected;
      const options = resolved.options;
      const approvalOptions = {
        approvedSafeClaims: stringRecord(options.approved_safe_claims),
      };
      if (expected.accepted === true) {
        const claimId = expected.claim_id;
        const approvalBasis = expected.approval_basis;
        const reviewerDecisionIds = expected.reviewer_decision_ids;
        const approvedSafeClaim = expected.approved_safe_claim;
        const disclosureDecision = expected.disclosure_decision;
        const disclosureAudience = expected.disclosure_audience;
        const disclosurePurpose = expected.disclosure_purpose;
        if (
          typeof claimId !== "string"
          || !isApprovalBasis(approvalBasis)
          || !Array.isArray(reviewerDecisionIds)
          || !reviewerDecisionIds.every((value) => typeof value === "string")
          || typeof approvedSafeClaim !== "string"
          || !isDisclosureDecision(disclosureDecision)
          || !isDisclosureAudienceOrNull(disclosureAudience)
          || (disclosurePurpose !== null && typeof disclosurePurpose !== "string")
        ) {
          throw new Error("malformed accepted approval expectation");
        }
        const result = approveClaims(resolved.evidence, resolved.reviews, approvalOptions);
        const claim = result.claims[0];
        if (claim === undefined) throw new Error("approval parity returned no claim");
        const expectedClaim = Object.fromEntries(Object.entries(expected).filter(([key]) => key !== "accepted"));
        expect(sameCanonical(claim, expectedClaim)).toBe(true);
        expect(claim.claim_id).toBe(claimId);
        expect(claim.approval_basis).toBe(approvalBasis);
        expect(claim.reviewer_decision_ids).toEqual(reviewerDecisionIds);
        expect(claim.approved_safe_claim).toBe(approvedSafeClaim);
        expect(claim.disclosure_decision).toBe(disclosureDecision);
        expect(claim.disclosure_audience).toBe(disclosureAudience);
        expect(claim.disclosure_purpose).toBe(disclosurePurpose);
      } else if (typeof expected.error_message === "string") {
        const expectedCode = expected.ts_error_code;
        if (typeof expectedCode !== "string") throw new Error("missing stable approval error code");
        try {
          approveClaims(resolved.evidence, resolved.reviews, approvalOptions);
          throw new Error("approval unexpectedly succeeded");
        } catch (error) {
          if (!(error instanceof KernelValidationError)) throw error;
          expect(error.message).toBe(expected.error_message);
          expect(error.code).toBe(expectedCode);
        }
      } else {
        const errorText = expected.error_contains;
        if (typeof errorText !== "string") throw new Error("missing approval rejection text");
        expect(() => approveClaims(resolved.evidence, resolved.reviews, approvalOptions)).toThrow(errorText);
      }
    }

    for (const item of kernelCasesDocument.lock_cases) {
      if (!isObject(item) || !isObject(item.expected)) throw new Error("malformed lock parity case");
      const exact = stringRecord(item.exact_final_claims);
      const mutated = stringRecord(item.mutated_final_claims);
      const expected = item.expected;
      if (expected.exact_accepted !== true || typeof expected.error_message !== "string" || typeof expected.ts_error_code !== "string") {
        throw new Error("malformed lock expectation");
      }
      const locked = lockApprovedClaims(item.approved_claims, exact);
      expect(locked.claims[0]?.approved_safe_claim).toBe(exact["claim.lock"]);
      try {
        lockApprovedClaims(item.approved_claims, mutated);
        throw new Error("lock mutation unexpectedly succeeded");
      } catch (error) {
        if (!(error instanceof KernelValidationError)) throw error;
        expect(error.message).toBe(expected.error_message);
        expect(error.code).toBe(expected.ts_error_code);
      }
    }

    for (const item of kernelCasesDocument.provenance_cases) {
      if (!isObject(item) || !Array.isArray(item.records) || !isStringArray(item.visible_claim_ids) || !isObject(item.expected)) {
        throw new Error("malformed provenance parity case");
      }
      if (!item.visible_claim_ids.every((value) => typeof value === "string")) {
        throw new Error("malformed provenance claim IDs");
      }
      if (!Array.isArray(item.expected.records)) throw new Error("malformed provenance expected records");
      expect(sameCanonical(buildProvenance(item.records, item.visible_claim_ids), item.expected.records)).toBe(true);
    }

    for (const item of kernelCasesDocument.closure_cases) {
      if (!isObject(item) || typeof item.approved_claim_case !== "string" || typeof item.evidence_case !== "string" || typeof item.review_case !== "string" || !isObject(item.expected)) {
        throw new Error("malformed provenance closure case");
      }
      const approvedSource = schemaCasesDocument.cases.find((candidate) => candidate.case_id === item.approved_claim_case);
      const evidenceSource = schemaCasesDocument.cases.find((candidate) => candidate.case_id === item.evidence_case);
      const reviewSource = schemaCasesDocument.cases.find((candidate) => candidate.case_id === item.review_case);
      if (!isObject(approvedSource) || !isObject(evidenceSource) || !isObject(reviewSource)) {
        throw new Error("unknown provenance closure source case");
      }
      const approved = mutableRecord(JSON.parse(JSON.stringify(approvedSource.input)), "approved closure input");
      if (typeof item.origin_evidence_override === "string") {
        if (!Array.isArray(approved.claims) || !isObject(approved.claims[0])) {
          throw new Error("malformed approved closure input");
        }
        const claim = mutableRecord(approved.claims[0], "approved closure claim");
        claim.origin_evidence_ids = [item.origin_evidence_override];
        approved.claims = [claim];
      }
      const approvedInput = validateSchemaDocument(approved, "approved-claims");
      if (!isStringArray(item.visible_claim_ids)) {
        throw new Error("malformed visible closure IDs");
      }
      expect(sameCanonical(
        checkProvenanceClosure(
          approvedInput,
          evidenceSource.input,
          reviewSource.input,
          item.visible_claim_ids,
        ),
        item.expected,
      )).toBe(true);
    }
  });

  test("preserves UTF-8 hashes and inclusive-line/half-open-byte spans", async () => {
    const fixture = manifest.source_fixtures;
    const record = fixture.record;
    if (typeof record !== "string") throw new Error("missing source fixture");
    const bytes = new Uint8Array(await Bun.file(join(GOLDEN_ROOT, record)).arrayBuffer());
    expect(sha256Bytes(bytes)).toBe(fixture.sha256);
    const spans = fixture.utf8_spans;
    if (!Array.isArray(spans)) throw new Error("missing UTF-8 spans");
    for (const expected of spans) {
      if (!isObject(expected)) throw new Error("malformed span fixture");
      const start = expected.start_byte;
      const end = expected.end_byte;
      const startLine = expected.start_line;
      const endLine = expected.end_line;
      const quote = expected.quote;
      if (
        typeof start !== "number"
        || typeof end !== "number"
        || typeof startLine !== "number"
        || typeof endLine !== "number"
        || typeof quote !== "string"
      ) {
        throw new Error("malformed UTF-8 span");
      }
      const span = sourceSpanFromBytes(bytes, start, end);
      expect(span.start_line).toBe(startLine);
      expect(span.end_line).toBe(endLine);
      expect(span.start_byte).toBe(start);
      expect(span.end_byte).toBe(end);
      expect(revalidateExactQuote(bytes, span, quote)).toBe(quote);
    }
  });

  test("canonical comparator ignores only declared nondeterminism", () => {
    expect(manifest.nondeterministic_fields).toEqual([
      "run.started_at",
      "run.finished_at",
      "run.directory_suffix",
      "artifact.generated_at",
    ]);
    expect(canonicalJsonText({ z: 1, a: { y: 2, x: 3 } })).toBe(
      '{\n  "a": {\n    "x": 3,\n    "y": 2\n  },\n  "z": 1\n}\n',
    );
    expect(sameCanonical(
      { claim_id: "claim.queue.extractive", approved_safe_claim: "Built a queue worker." },
      { claim_id: "claim.queue.extractive", approved_safe_claim: "Owned a queue worker." },
    )).toBe(false);
  });

  test("checks policy, approval, provenance, variants, rendering, and IO expectations", () => {
    const policy = manifest.policy_cases;
    if (!Array.isArray(policy)) throw new Error("missing policy fixtures");
    const inherited = policy.find((item) => isObject(item) && item.case_id === "inherited-f6-p3");
    expect(inherited?.effective_fact_policy).toBe("F6");
    expect(inherited?.effective_disclosure_policy).toBe("P3");
    expect(inherited?.decision).toBe("denied");
    const p2 = policy.find((item) => isObject(item) && item.case_id === "p2-without-confirmation");
    expect(p2?.user_confirmation_required).toBe(true);

    const approvals = manifest.approval_cases;
    if (!Array.isArray(approvals)) throw new Error("missing approval fixtures");
    for (const item of approvals) expect(item.locked).toBe(true);
    const semantic = approvals.find((item) => isObject(item) && item.case_id === "reviewed-semantic-independent");
    expect(semantic?.claim_mode).toBe("reviewed-semantic");
    expect(semantic?.reviewer_decision_ids).toEqual(["review.evidence.queue"]);

    const provenance = manifest.provenance_cases;
    if (!Array.isArray(provenance)) throw new Error("missing provenance fixtures");
    const missing = provenance.find((item) => isObject(item) && item.case_id === "missing-origin-rejected");
    expect((missing?.expected as JsonObject).closed).toBe(false);

    const variants = manifest.variants;
    if (!isObject(variants) || !isObject(variants.all)) throw new Error("missing variant fixtures");
    const all = variants.all.variants;
    if (!Array.isArray(all)) throw new Error("missing variants");
    expect(all.map((item) => (item as JsonObject).variant)).toEqual([
      "recruiter-one-page",
      "technical-two-page",
      "extended-three-page",
    ]);
    expect(((all[0] as JsonObject).artifacts as JsonObject).pdf).toBe("resume-recruiter-1p.pdf");
    expect(((all[2] as JsonObject).artifacts as JsonObject).pdf).toBe("technical-profile-3p.pdf");

    const partial = variants["partial-failure"];
    if (!isObject(partial) || !isObject(partial.manifest)) throw new Error("missing partial manifest");
    const partialVariants = partial.manifest.variants;
    if (!Array.isArray(partialVariants)) throw new Error("missing partial variant records");
    const failedVariant = partialVariants[1];
    if (!isObject(failedVariant)) throw new Error("missing failed variant record");
    expect(failedVariant.actual_pages).toBe(4);
    expect(failedVariant.pdf_success).toBe(false);
    expect((failedVariant.artifacts as JsonObject).pdf).toBe("resume-technical-2p.pdf");
    const audit = manifest.audit_cases;
    if (!Array.isArray(audit)) throw new Error("missing audit fixtures");
    expect(audit.find((item) => isObject(item) && item.case_id === "clean-semantic-audit")?.success).toBe(true);
    expect(audit.find((item) => isObject(item) && item.case_id === "unsupported-and-placeholder")?.success).toBe(false);
    const html = manifest.html_cases?.[0];
    expect(html?.expected_text_order).toEqual([
      "Synthetic Candidate",
      "Platform Engineer",
      "Summary",
      "Skills",
      "Experience",
      "Projects",
      "Education",
      "Honors",
    ]);
    const pdf = manifest.pdf_cases?.find((item) => isObject(item) && item.case_id === "pdf-overflow-and-blank");
    expect(pdf?.blank_pages).toEqual([2]);
    expect(pdf?.overflow).toBe(true);

    const io = manifest.io_cases;
    if (!Array.isArray(io)) throw new Error("missing IO fixtures");
    expect(io.find((item) => isObject(item) && item.case_id === "private-modes")?.directory_mode).toBe("0700");
    expect(io.find((item) => isObject(item) && item.case_id === "symlink-rejected")?.accepted).toBe(false);
    expect(io.find((item) => isObject(item) && item.case_id === "atomic-non-overwrite")?.existing_bytes_preserved).toBe(true);
  });

  test("verification matrix and explicit hybrid backend remain complete", () => {
    const required = new Set([
      "known-adapter",
      "heterogeneous-agent-assisted",
      "extractive-claims",
      "reviewed-semantic",
      "unsupported-claim",
      "inherited-f6-p3",
      "fenced-example",
      "p2-confirmation",
      "stale-conflicting-jd",
      "all-variants",
      "partial-manifest-failure",
    ]);
    const matrix = manifest.verification_matrix;
    expect(new Set(matrix.map((item) => item.case_id))).toEqual(required);
    for (const item of matrix) {
      expect(typeof item.expected_backend).toBe("string");
      expect(typeof item.expected).toBe("string");
    }
    expect(manifest.backend_matrix).toMatchObject({
      "schema-validation": "typescript",
      normalization: "typescript",
      "secure-io": "typescript",
      "source-map-parser": "python",
      "role-input-validation": "python",
      "evidence-input-validation": "python",
      "policy-approval-provenance": "typescript",
      composition: "python",
      "pdf-inspection": "python-pymupdf",
      "semantic-audit": "python",
    });
  });
});
