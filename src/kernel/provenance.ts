import {
  type ApprovedClaimsIR,
  type NormalizedEvidenceInput,
  normalizeApprovedClaims,
  normalizeEvidenceInput,
  normalizeReviewDecisions,
} from "./approval.ts";
import {
  applyEvidencePolicy,
  detectSensitiveContent,
  type DisclosurePolicy,
  type FactPolicy,
  type OutputMode,
} from "./policy.ts";

export interface ProvenanceRecord {
  readonly claim_id: string;
  readonly evidence_ids: readonly string[];
  readonly source_refs: readonly string[];
  readonly fact_state: FactPolicy;
  readonly disclosure: DisclosurePolicy;
  readonly output_mode: OutputMode;
  readonly rendered_claim: string;
  readonly transformations: readonly string[];
}

export interface ProvenanceClosureResult {
  readonly closed: boolean;
  readonly missing: readonly string[];
  readonly missing_origin_evidence_ids: readonly string[];
  readonly missing_review_decision_ids: readonly string[];
  readonly missing_source_evidence_ids: readonly string[];
  readonly uncovered_claim_ids: readonly string[];
}

export class ProvenanceValidationError extends Error {
  readonly code = "PROVENANCE_NOT_CLOSED";
  readonly result: ProvenanceClosureResult;

  constructor(result: ProvenanceClosureResult) {
    const details = [
      result.missing_origin_evidence_ids.length > 0
        ? `missing origin evidence IDs: ${JSON.stringify(result.missing_origin_evidence_ids)}`
        : "",
      result.missing_review_decision_ids.length > 0
        ? `missing review decision IDs: ${JSON.stringify(result.missing_review_decision_ids)}`
        : "",
      result.missing_source_evidence_ids.length > 0
        ? `evidence without owning source identity: ${JSON.stringify(result.missing_source_evidence_ids)}`
        : "",
      result.uncovered_claim_ids.length > 0
        ? `visible claims without approved provenance: ${JSON.stringify(result.uncovered_claim_ids)}`
        : "",
    ].filter((detail) => detail.length > 0);
    super(`provenance is not closed${details.length > 0 ? `: ${details.join("; ")}` : ""}`);
    this.name = "ProvenanceValidationError";
    this.result = result;
  }
}

function objectValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function field(value: unknown, name: string, fallback?: unknown): unknown {
  const data = objectValue(value);
  return data[name] === undefined ? fallback : data[name];
}

function stringValues(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return Object.freeze([]);
  return Object.freeze(value.filter((item): item is string => typeof item === "string" && item.length > 0));
}

function outputMode(value: unknown, fallback: OutputMode): OutputMode | null {
  const mode = value === undefined || value === null ? fallback : String(value);
  if (mode !== "targeted_application" && mode !== "public_portfolio" && mode !== "master_resume") return null;
  return mode;
}

function sourceReference(value: unknown): string | null {
  const source = field(value, "source");
  const path = field(source, "path");
  const section = field(source, "section", field(source, "section_id", field(source, "block_id")));
  const hashValue = field(source, "source_hash");
  if (typeof path !== "string" || path.length === 0 || typeof section !== "string" || section.length === 0) return null;
  if (typeof hashValue !== "string" || hashValue.length === 0) return null;
  const sourceHash = hashValue.startsWith("sha256:") ? hashValue : `sha256:${hashValue}`;
  return `${path}#${section}@${sourceHash}`;
}

function factPolicy(value: unknown): FactPolicy | null {
  return value === "F1" || value === "F2" || value === "F3" || value === "F4" || value === "F5" || value === "F6"
    ? value
    : null;
}

function disclosurePolicy(value: unknown): DisclosurePolicy | null {
  return value === "P0" || value === "P1" || value === "P2" || value === "P3" ? value : null;
}

export function buildProvenance(
  records: readonly unknown[],
  visibleClaimIds: readonly string[],
  mode: OutputMode = "targeted_application",
): readonly ProvenanceRecord[] {
  const visible = new Set(visibleClaimIds);
  const result: ProvenanceRecord[] = [];
  for (const raw of records) {
    const rawData = objectValue(raw);
    const existingSourceRefs = stringValues(rawData.source_refs);
    const looksCanonical = existingSourceRefs.length > 0 && typeof rawData.rendered_claim === "string";
    if (looksCanonical) {
      const claimId = typeof rawData.claim_id === "string" ? rawData.claim_id : "";
      const fact = factPolicy(rawData.fact_state);
      const disclosure = disclosurePolicy(rawData.disclosure);
      const recordMode = outputMode(rawData.output_mode, mode);
      const evidenceIds = stringValues(rawData.evidence_ids);
      const renderedClaim = typeof rawData.rendered_claim === "string" ? rawData.rendered_claim : "";
      if (claimId.length === 0 || !visible.has(claimId) || fact === null || disclosure === null || recordMode === null) continue;
      if (evidenceIds.length === 0 || renderedClaim.length === 0 || detectSensitiveContent(renderedClaim)) continue;
      const decision = applyEvidencePolicy(rawData, recordMode);
      if (!decision.allowed_in_output) continue;
      result.push(Object.freeze({
        claim_id: claimId,
        evidence_ids: Object.freeze([...new Set(evidenceIds)]),
        source_refs: Object.freeze([...new Set(existingSourceRefs)]),
        fact_state: fact,
        disclosure,
        output_mode: recordMode,
        rendered_claim: renderedClaim,
        transformations: Object.freeze([...stringValues(rawData.transformations)]),
      }));
      continue;
    }

    const claimIdValue = rawData.claim_id ?? rawData.evidence_id;
    const claimId = typeof claimIdValue === "string" ? claimIdValue : "";
    if (claimId.length === 0 || !visible.has(claimId)) continue;
    const recordMode = outputMode(rawData.output_mode, mode);
    if (recordMode === null || !applyEvidencePolicy(rawData, recordMode).allowed_in_output) continue;
    const sourceRef = sourceReference(rawData);
    if (sourceRef === null) continue;
    const evidenceId = typeof rawData.evidence_id === "string" ? rawData.evidence_id : "";
    const renderedValue = rawData.rendered_claim ?? rawData.safe_claim;
    const renderedClaim = typeof renderedValue === "string" ? renderedValue : "";
    const fact = factPolicy(rawData.fact_state);
    const disclosure = disclosurePolicy(rawData.disclosure ?? rawData.disclosure_level);
    if (
      evidenceId.length === 0
      || renderedClaim.length === 0
      || detectSensitiveContent(renderedClaim)
      || fact === null
      || disclosure === null
    ) continue;
    const submittedEvidenceIds = stringValues(rawData.evidence_ids);
    result.push(Object.freeze({
      claim_id: claimId,
      evidence_ids: Object.freeze([...new Set(submittedEvidenceIds.length > 0 ? submittedEvidenceIds : [evidenceId])]),
      source_refs: Object.freeze([sourceRef]),
      fact_state: fact,
      disclosure,
      output_mode: recordMode,
      rendered_claim: renderedClaim,
      transformations: Object.freeze([...stringValues(rawData.transformations)]),
    }));
  }
  return Object.freeze(result);
}

export function checkProvenanceClosure(
  approvedClaimsValue: unknown,
  evidenceInputValue: unknown,
  reviewDecisionsValue: unknown = { schema_version: 1, decisions: [] },
  visibleClaimIds?: readonly string[],
): ProvenanceClosureResult {
  const approved = normalizeApprovedClaims(approvedClaimsValue);
  const evidence = normalizeEvidenceInput(evidenceInputValue);
  const reviews = normalizeReviewDecisions(reviewDecisionsValue);
  const evidenceById = new Map(evidence.candidates.map((candidate) => [candidate.evidence_id, candidate]));
  const reviewIds = new Set(reviews.decisions.map((review) => review.review_id));
  const approvedClaimIds = new Set(approved.claims.map((claim) => claim.claim_id));
  const missingOrigins = new Set<string>();
  const missingReviews = new Set<string>();
  const missingSources = new Set<string>();

  for (const claim of approved.claims) {
    for (const evidenceId of claim.origin_evidence_ids) {
      const origin = evidenceById.get(evidenceId);
      if (origin === undefined) {
        missingOrigins.add(evidenceId);
        continue;
      }
      if (
        origin.source.path.length === 0
        || origin.source.source_hash.length === 0
        || origin.source.exact_quote.length === 0
        || (origin.source.section_id === null && origin.source.block_id === null)
      ) {
        missingSources.add(evidenceId);
      }
    }
    for (const reviewId of claim.reviewer_decision_ids) {
      if (!reviewIds.has(reviewId)) missingReviews.add(reviewId);
    }
  }
  const visible = visibleClaimIds ?? approved.claims.map((claim) => claim.claim_id);
  const uncovered = new Set(visible.filter((claimId) => !approvedClaimIds.has(claimId)));
  const missingOriginEvidenceIds = Object.freeze([...missingOrigins].sort());
  const missingReviewDecisionIds = Object.freeze([...missingReviews].sort());
  const missingSourceEvidenceIds = Object.freeze([...missingSources].sort());
  const uncoveredClaimIds = Object.freeze([...uncovered].sort());
  const missing = Object.freeze([
    ...missingOriginEvidenceIds,
    ...missingReviewDecisionIds,
    ...missingSourceEvidenceIds,
    ...uncoveredClaimIds,
  ].filter((value, index, values) => values.indexOf(value) === index).sort());
  return Object.freeze({
    closed: missing.length === 0,
    missing,
    missing_origin_evidence_ids: missingOriginEvidenceIds,
    missing_review_decision_ids: missingReviewDecisionIds,
    missing_source_evidence_ids: missingSourceEvidenceIds,
    uncovered_claim_ids: uncoveredClaimIds,
  });
}

export function assertProvenanceClosure(
  approvedClaimsValue: unknown,
  evidenceInputValue: unknown,
  reviewDecisionsValue: unknown = { schema_version: 1, decisions: [] },
  visibleClaimIds?: readonly string[],
): ProvenanceClosureResult {
  const result = checkProvenanceClosure(
    approvedClaimsValue,
    evidenceInputValue,
    reviewDecisionsValue,
    visibleClaimIds,
  );
  if (!result.closed) throw new ProvenanceValidationError(result);
  return result;
}

export function buildApprovedClaimsProvenance(
  approvedClaimsValue: unknown,
  evidenceInputValue: unknown,
  reviewDecisionsValue: unknown = { schema_version: 1, decisions: [] },
  mode: OutputMode = "targeted_application",
): readonly ProvenanceRecord[] {
  const approved: ApprovedClaimsIR = normalizeApprovedClaims(approvedClaimsValue);
  const evidence: NormalizedEvidenceInput = normalizeEvidenceInput(evidenceInputValue);
  assertProvenanceClosure(approved, evidence, reviewDecisionsValue);
  const evidenceById = new Map(evidence.candidates.map((candidate) => [candidate.evidence_id, candidate]));
  const records = approved.claims.map((claim) => {
    const firstOriginId = claim.origin_evidence_ids[0];
    const origin = firstOriginId === undefined ? undefined : evidenceById.get(firstOriginId);
    if (origin === undefined) throw new ProvenanceValidationError(checkProvenanceClosure(approved, evidence, reviewDecisionsValue));
    const section = origin.source.section_id ?? origin.source.block_id;
    if (section === null) throw new ProvenanceValidationError(checkProvenanceClosure(approved, evidence, reviewDecisionsValue));
    return {
      claim_id: claim.claim_id,
      evidence_id: claim.claim_id,
      evidence_ids: claim.origin_evidence_ids,
      source: {
        path: origin.source.path,
        section,
        source_hash: origin.source.source_hash,
      },
      fact_state: origin.source.structural_flags.effective_fact_policy,
      disclosure: origin.source.structural_flags.effective_disclosure_policy,
      output_mode: mode,
      rendered_claim: claim.approved_safe_claim,
      transformations: [],
    };
  });
  return buildProvenance(records, approved.claims.map((claim) => claim.claim_id), mode);
}

export function buildConfirmationQuestions(
  records: readonly unknown[],
  constraints: readonly unknown[] = [],
  limit = 6,
): readonly string[] {
  if (limit <= 0) return Object.freeze([]);
  const questions: string[] = [];
  for (const record of records) {
    const fact = String(field(record, "fact_state", "F5")).toUpperCase();
    const disclosure = String(field(record, "disclosure", field(record, "disclosure_level", "P3"))).toUpperCase();
    const claimValue = field(record, "safe_claim", field(record, "proposed_claim", ""));
    const claim = typeof claimValue === "string" ? claimValue.trim() : String(claimValue ?? "").trim();
    const freshness = field(record, "freshness");
    const stale = Boolean(field(freshness, "stale", false));
    const dynamicUnchecked = Boolean(field(freshness, "dynamic", false)) && !field(freshness, "checked_at");
    if (disclosure === "P3" || fact === "F6" || detectSensitiveContent(claim)) continue;
    const evidenceValue = field(record, "evidence_id", field(record, "candidate_id", "this claim"));
    const evidenceId = String(evidenceValue);
    if (fact === "F4") {
      questions.push(`Can you confirm the scope and accuracy of ${evidenceId}: ${claim}?`);
    } else if (fact === "F5") {
      questions.push(`What owning source can confirm ${evidenceId}: ${claim}?`);
    } else if (fact === "F3" && (stale || dynamicUnchecked)) {
      questions.push(`Is ${evidenceId} still current, and when was it last verified: ${claim}?`);
    }
    if (questions.length >= limit) return Object.freeze(questions);
  }
  for (const constraint of constraints) {
    const status = String(field(constraint, "status", "unknown")).toLowerCase();
    if (status !== "unknown") continue;
    const constraintId = String(field(constraint, "constraint_id", "constraint"));
    const kind = String(field(constraint, "kind", "application constraint"));
    questions.push(`Can you confirm ${kind} for ${constraintId} and provide current evidence?`);
    if (questions.length >= limit) break;
  }
  return Object.freeze(questions);
}
