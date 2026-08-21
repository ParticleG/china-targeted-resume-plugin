import { describe, expect, test } from "bun:test";
import {
  approveAndLockClaims,
  approveClaims,
  deriveConfirmationRequests,
  KernelValidationError,
  lockApprovedClaims,
  normalizeExtractiveClaim,
  verifyApprovalLock,
  type ApproveClaimsOptions,
  type ConfirmationRequest,
  type ReviewDecision,
} from "../../src/kernel/approval.ts";
import {
  applyEvidencePolicy,
  assertProposalDomain,
  assertVariantConstraints,
  expectedResumeVariants,
  parsePolicyMarkers,
  resolveEffectivePolicy,
} from "../../src/kernel/policy.ts";
import {
  assertProvenanceClosure,
  buildApprovedClaimsProvenance,
  checkProvenanceClosure,
} from "../../src/kernel/provenance.ts";

const SOURCE_HASH = "sha256:addd9e85b3a41264842ae96705a2d6b8e15d52bd47749dec3d19c72efbd83fdd";
const EXACT_QUOTE = "- Built a queue worker for 样例服务.\n";

function evidenceInput(overrides: {
  readonly claimMode?: "extractive" | "reviewed-semantic";
  readonly disclosure?: "P0" | "P2" | "P3";
  readonly fact?: "F1" | "F2" | "F3" | "F4" | "F5" | "F6";
  readonly owner?: "candidate" | "team" | "organization" | "unknown";
  readonly unresolvedQuestions?: readonly string[];
  readonly inputUnresolvedQuestions?: readonly string[];
  readonly proposedClaim?: string;
} = {}) {
  return {
    schema_version: 1,
    input_id: "evidence-input.queue",
    domain: "evidence",
    candidates: [{
      evidence_id: "evidence.queue",
      proposal_id: "proposal.queue",
      source: {
        path: "sources/record.md",
        source_hash: SOURCE_HASH,
        span: { start_line: 3, end_line: 3, start_byte: 12, end_byte: 53 },
        exact_quote: EXACT_QUOTE,
        structural_flags: {
          block_kind: "list_item",
          inside_fence: false,
          inside_blockquote: false,
          inside_html: false,
          is_example: false,
          is_template: false,
          is_quoted: false,
          negative_instruction: false,
          secret_path: false,
          secret_content: false,
          malformed: false,
          effective_fact_policy: overrides.fact ?? "F1",
          effective_disclosure_policy: overrides.disclosure ?? "P0",
        },
        heading_ancestry: ["Evidence"],
        section_id: "section.evidence",
        block_id: "block.queue",
      },
      proposed_claim: overrides.proposedClaim ?? EXACT_QUOTE,
      domain: "evidence",
      owner: overrides.owner ?? "candidate",
      confidence: 1,
      reasoning: "Synthetic exact source-backed evidence.",
      claim_mode: overrides.claimMode ?? "extractive",
      requirement_ids: ["requirement.queue"],
      contribution_qualifiers: [],
      metric_qualifiers: [],
      unresolved_questions: [...(overrides.unresolvedQuestions ?? [])],
    }],
    unresolved_questions: [...(overrides.inputUnresolvedQuestions ?? [])],
  };
}

function reviewDecision(
  kind: "evidence" | "contribution_metric" | "privacy",
  reviewerId: string,
  overrides: Partial<ReviewDecision> = {},
): ReviewDecision {
  return {
    review_id: `review.${kind}.queue`,
    evidence_id: "evidence.queue",
    reviewer_id: reviewerId,
    review_kind: kind,
    outcome: "approve",
    reasoning: `Synthetic ${kind} approval.`,
    approved_safe_claim: EXACT_QUOTE,
    contribution_qualifiers: [],
    metric_qualifiers: [],
    disclosure_decision: kind === "privacy" ? "allowed" : null,
    disclosure_audience: kind === "privacy" ? "hiring_team" : null,
    disclosure_purpose: kind === "privacy" ? "targeted_application" : null,
    user_confirmation_required: false,
    user_confirmed: false,
    questions: [],
    ...overrides,
  };
}

function independentReviews() {
  return {
    schema_version: 1,
    decisions: [
      reviewDecision("evidence", "reviewer.evidence", {
        approved_safe_claim: "Built and operated a queue worker for 样例服务.",
      }),
      reviewDecision("contribution_metric", "reviewer.contribution", {
        approved_safe_claim: "Built and operated a queue worker for 样例服务.",
      }),
      reviewDecision("privacy", "reviewer.privacy", {
        approved_safe_claim: "Built and operated a queue worker for 样例服务.",
      }),
    ],
  };
}

function confirmationReceipt(request: ConfirmationRequest) {
  return {
    ...request,
    confirmed_by: "interactive_user" as const,
    confirmed: true as const,
    confirmed_at: "2026-08-21T12:00:00.000Z",
    nonce: `nonce.${request.evidence_id}`,
  };
}

const reviewedOptions: ApproveClaimsOptions = {
  approvedSafeClaims: { "evidence.queue": "Built and operated a queue worker for 样例服务." },
};

const request = {
  schema_version: 1,
  source_root: "/tmp/source",
  output_root: "/tmp/output",
  output_mode: "targeted_application",
  include_extended_profile: false,
};

describe("deterministic policy kernel", () => {
  test("uses the most restrictive explicit and inherited F/P policy", () => {
    expect(parsePolicyMarkers("F1 reviewed, but section boundary is F6; P0 then P3")).toEqual({
      fact: "F6",
      disclosure: "P3",
    });
    expect(parsePolicyMarkers("no marker")).toEqual({ fact: "F5", disclosure: "P3" });

    expect(resolveEffectivePolicy({
      document_fact_policy: "F1",
      document_disclosure_policy: "P0",
      ancestor_fact_policy: "F6",
      ancestor_disclosure_policy: "P3",
    })).toEqual({
      effective_fact_policy: "F6",
      effective_disclosure_policy: "P3",
      blocked: true,
      decision: "denied",
      user_confirmation_required: false,
      blocking_reasons: ["fact_policy:F6", "disclosure_policy:P3"],
    });
  });

  test("rejects unknown runtime policy markers instead of failing open", () => {
    expect(() => resolveEffectivePolicy({
      document_fact_policy: "F9" as never,
      document_disclosure_policy: "P0",
    })).toThrow('unknown fact policy "F9"');
    expect(() => resolveEffectivePolicy({
      document_fact_policy: "F1",
      document_disclosure_policy: "P9" as never,
    })).toThrow('unknown disclosure policy "P9"');
  });

  test("keeps P2 confirmation and output mode as hard gates", () => {
    expect(resolveEffectivePolicy({
      document_fact_policy: "F2",
      document_disclosure_policy: "P2",
    })).toMatchObject({
      effective_fact_policy: "F2",
      effective_disclosure_policy: "P2",
      blocked: true,
      decision: "needs_confirmation",
      user_confirmation_required: true,
      blocking_reasons: ["p2_permission_unknown"],
    });
    expect(resolveEffectivePolicy({
      document_fact_policy: "F2",
      document_disclosure_policy: "P2",
      p2_confirmed: true,
      output_mode: "public_portfolio",
    })).toMatchObject({ decision: "denied", blocking_reasons: ["targeted_application_only"] });
  });

  test("fails closed across role and evidence domains", () => {
    expect(assertProposalDomain("evidence", "evidence-input")).toBe("evidence");
    expect(assertProposalDomain("job-description", "role-input")).toBe("job-description");
    expect(() => assertProposalDomain("company", "evidence-input")).toThrow("forbidden domain");
    expect(() => assertProposalDomain("evidence", "role-input")).toThrow("forbidden domain");
  });

  test("matches fail-closed evidence output gates without echoing sensitive records", () => {
    expect(applyEvidencePolicy({
      fact_state: "F3",
      disclosure: "P1",
      safe_claim: "Synthetic current claim",
      verified_at: "2026-08-01T00:00:00Z",
      expires_at: "2026-09-01T00:00:00Z",
    }, "targeted_application", { now: "2026-08-21T00:00:00Z" })).toMatchObject({
      allowed_as_candidate: true,
      allowed_in_output: true,
      current_verification_required: true,
    });
    expect(applyEvidencePolicy({
      fact_state: "F1",
      disclosure: "P0",
      safe_claim: "password=FIXTURE_SECRET",
    }, "targeted_application")).toMatchObject({
      allowed_as_candidate: false,
      allowed_in_output: false,
      record: null,
      reason_codes: ["sensitive_content_detected"],
    });
  });

  test("selects exactly the two defaults and opt-in extended artifact contract", () => {
    const defaults = expectedResumeVariants(request);
    expect(defaults.map((variant) => variant.variant)).toEqual([
      "recruiter-one-page",
      "technical-two-page",
    ]);
    expect(defaults[0]?.artifacts.pdf).toBe("resume-recruiter-1p.pdf");
    const extendedRequest = { ...request, include_extended_profile: true };
    expect(expectedResumeVariants(extendedRequest)[2]).toMatchObject({
      variant: "extended-three-page",
      base_name: "technical-profile-3p",
      target_pages: 3,
    });
    expect(() => assertVariantConstraints(request, [
      "recruiter-one-page",
      "technical-two-page",
      "extended-three-page",
    ])).toThrow("exactly 2");
  });
});

describe("approval and exact lock kernel", () => {
  test("permits only exact mechanical whitespace/list-marker normalization", () => {
    expect(normalizeExtractiveClaim(EXACT_QUOTE, "Built a queue worker for 样例服务.")).toBe(
      "Built a queue worker for 样例服务.",
    );
    expect(() => normalizeExtractiveClaim(EXACT_QUOTE, "Owned the queue platform.")).toThrow(
      "not an exact quote",
    );
  });

  test("mechanical approval locks final text byte-for-byte", () => {
    const approved = approveClaims(evidenceInput(), { schema_version: 1, decisions: [] });
    expect(approved.claims[0]).toMatchObject({
      claim_id: "claim.evidence.queue",
      approved_safe_claim: EXACT_QUOTE,
      approval_basis: "mechanical",
      reviewer_decision_ids: [],
      claim_mode: "extractive",
    });
    expect(lockApprovedClaims(approved, { "claim.evidence.queue": EXACT_QUOTE })).toEqual(approved);
    expect(() => lockApprovedClaims(approved, {
      "claim.evidence.queue": EXACT_QUOTE.trim(),
    })).toThrow("exactly equal");
  });

  test("rejects F3/F4/F5 before any claim can be locked", () => {
    const cases = [
      ["F3", "F3_CURRENT_VERIFICATION_REQUIRED", "evidence 'evidence.queue': fact policy F3 requires parser-revalidated current freshness proof before approval"],
      ["F4", "F4_UNCONFIRMED_FACT", "evidence 'evidence.queue': fact policy F4 is unapprovable without a confirmed fact state"],
      ["F5", "F5_UNSUPPORTED_FACT", "evidence 'evidence.queue': fact policy F5 is unapprovable without a confirmed fact state"],
    ] as const;
    for (const [fact, code, message] of cases) {
      let rejection: unknown;
      try {
        approveClaims(evidenceInput({ fact }), { schema_version: 1, decisions: [] });
      } catch (error) {
        rejection = error;
      }
      expect(rejection).toBeInstanceOf(KernelValidationError);
      expect((rejection as KernelValidationError).code).toBe(code);
      expect((rejection as Error).message).toBe(message);
    }
  });

  test("rejects non-candidate ownership until reviewed IR resolves it", () => {
    for (const owner of ["team", "organization", "unknown"] as const) {
      let rejection: unknown;
      try {
        approveClaims(evidenceInput({ owner }), { schema_version: 1, decisions: [] });
      } catch (error) {
        rejection = error;
      }
      expect(rejection).toBeInstanceOf(KernelValidationError);
      expect((rejection as KernelValidationError).code).toBe("EVIDENCE_OWNER_NOT_CANDIDATE");
      expect((rejection as Error).message).toBe(
        `evidence 'evidence.queue': owner ${owner} is not candidate; ownership must be resolved in reviewed candidate IR`,
      );
    }
  });
  test("rejects unresolved extractive and input-level questions before locking", () => {
    const cases = [
      {
        evidence: evidenceInput({ unresolvedQuestions: ["Confirm contribution scope"] }),
        code: "EXTRACTIVE_UNRESOLVED_QUESTIONS",
        message: "evidence 'evidence.queue': extractive approval cannot proceed with unresolved questions",
      },
      {
        evidence: evidenceInput({ inputUnresolvedQuestions: ["Confirm owning source"] }),
        code: "EVIDENCE_INPUT_UNRESOLVED_QUESTIONS",
        message: "normalized evidence input 'evidence-input.queue' has unresolved questions; approval fails closed until revalidated",
      },
    ];
    for (const item of cases) {
      let rejection: unknown;
      try {
        approveClaims(item.evidence, { schema_version: 1, decisions: [] });
      } catch (error) {
        rejection = error;
      }
      expect(rejection).toBeInstanceOf(KernelValidationError);
      expect((rejection as KernelValidationError).code).toBe(item.code);
      expect((rejection as Error).message).toBe(item.message);
    }
  });


  test("unsupported, P3, disagreement, and non-independent reviewers fail closed", () => {
    expect(() => approveClaims(evidenceInput({ disclosure: "P3" }), {
      schema_version: 1,
      decisions: [],
    })).toThrow("blocked structural policy");

    const disagreement = independentReviews();
    disagreement.decisions[0] = reviewDecision("evidence", "reviewer.evidence", { outcome: "disagree" });
    expect(() => approveClaims(
      evidenceInput({ claimMode: "reviewed-semantic" }),
      disagreement,
      reviewedOptions,
    )).toThrow("disagreement/rejection");

    const correlated = independentReviews();
    correlated.decisions[1] = reviewDecision("contribution_metric", "reviewer.evidence");
    expect(() => approveClaims(
      evidenceInput({ claimMode: "reviewed-semantic" }),
      correlated,
      reviewedOptions,
    )).toThrow("must be independent");
  });

  test("binds every approving review to exact text and preserves reviewer qualifiers", () => {
    const evidence = evidenceInput({ claimMode: "reviewed-semantic" });
    const reviews = independentReviews();
    const contribution = reviews.decisions[1]!;
    reviews.decisions[1] = {
      ...contribution,
      contribution_qualifiers: [{ text: "Personally implemented", scope: "worker", actor: "candidate" }],
      metric_qualifiers: [{ text: "test scope", name: "latency", value: "20", unit: "%", qualifier: "test" }],
    };
    const approved = approveClaims(evidence, reviews, reviewedOptions);
    expect(approved.claims[0]?.contribution_qualifiers).toEqual([
      { text: "Personally implemented", scope: "worker", actor: "candidate" },
    ]);
    expect(approved.claims[0]?.metric_qualifiers).toEqual([
      { text: "test scope", name: "latency", value: "20", unit: "%", qualifier: "test" },
    ]);

    const missingBindingReviews = {
      ...reviews,
      decisions: reviews.decisions.map((review, index) => index === 0
        ? { ...review, approved_safe_claim: null }
        : review),
    };
    const forgedAttempts = [
      {
        reviews,
        options: { approvedSafeClaims: { "evidence.queue": "Changed after reviews approved another claim." } },
      },
      { reviews: missingBindingReviews, options: reviewedOptions },
    ];
    for (const attempt of forgedAttempts) {
      let rejection: unknown;
      try {
        approveClaims(evidence, attempt.reviews, attempt.options);
      } catch (error) {
        rejection = error;
      }
      expect(rejection).toBeInstanceOf(KernelValidationError);
      expect((rejection as KernelValidationError).code).toBe("REVIEW_CLAIM_BINDING_MISMATCH");
      expect((rejection as Error).message).toBe(
        "evidence 'evidence.queue': approved_safe_claim does not exactly match all approving reviews",
      );
    }
  });

  test("P2 extractive approval requires trusted confirmation and preserves its privacy review", () => {
    const evidence = evidenceInput({ disclosure: "P2" });
    const reviews = {
      schema_version: 1,
      decisions: [reviewDecision("privacy", "reviewer.privacy")],
    };
    const runId = "run.p2-extractive";
    const requests = deriveConfirmationRequests(runId, evidence, reviews, {
      outputMode: "targeted_application",
    });
    expect(requests).toHaveLength(1);
    let rejection: unknown;
    try {
      approveClaims(evidence, reviews, { runId, outputMode: "targeted_application" });
    } catch (error) {
      rejection = error;
    }
    expect(rejection).toBeInstanceOf(KernelValidationError);
    expect((rejection as KernelValidationError).code).toBe("P2_CONFIRMATION_REQUIRED");
    expect((rejection as Error).message).toBe(
      "evidence 'evidence.queue': P2 approval requires a same-run user confirmation receipt",
    );

    const approved = approveClaims(evidence, reviews, {
      runId,
      outputMode: "targeted_application",
      confirmationReceipts: requests.map(confirmationReceipt),
    });
    expect(approved.claims[0]).toMatchObject({
      approval_basis: "user_confirmed",
      claim_mode: "extractive",
      reviewer_decision_ids: ["review.privacy.queue"],
      approved_safe_claim: EXACT_QUOTE,
    });
  });

  test("P2 reviewed-semantic approval requires a claim-bound confirmation receipt", () => {
    const evidence = evidenceInput({ claimMode: "reviewed-semantic", disclosure: "P2" });
    const reviews = independentReviews();
    const runId = "run.p2-reviewed";
    const requests = deriveConfirmationRequests(runId, evidence, reviews, {
      ...(reviewedOptions.approvedSafeClaims === undefined
        ? {}
        : { approvedSafeClaims: reviewedOptions.approvedSafeClaims }),
      outputMode: "targeted_application",
    });
    expect(() => approveClaims(evidence, reviews, {
      ...reviewedOptions,
      runId,
      outputMode: "targeted_application",
    })).toThrow("same-run user confirmation receipt");
    const approved = approveClaims(evidence, reviews, {
      ...reviewedOptions,
      runId,
      outputMode: "targeted_application",
      confirmationReceipts: requests.map(confirmationReceipt),
    });
    expect(approved.claims[0]?.approval_basis).toBe("user_confirmed");
    expect(approved.claims[0]?.approved_safe_claim).toBe(reviewedOptions.approvedSafeClaims?.["evidence.queue"]);
  });

  test("digest binds same run, full evidence/reviews/confirmations, and exact claims", () => {
    const evidence = evidenceInput({ claimMode: "reviewed-semantic" });
    const reviews = independentReviews();
    const result = approveAndLockClaims("run.approval", evidence, reviews, reviewedOptions);
    expect(result.backend).toBe("typescript");
    expect(result.approval_lock.digest).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(verifyApprovalLock(
      "run.approval",
      result.approval_lock,
      evidence,
      reviews,
      result.approved_claims,
      reviewedOptions,
    )).toEqual(result.approval_lock);

    expect(() => verifyApprovalLock(
      "run.other",
      result.approval_lock,
      evidence,
      reviews,
      result.approved_claims,
      reviewedOptions,
    )).toThrow("different run");

    const mutatedClaims = {
      ...result.approved_claims,
      claims: result.approved_claims.claims.map((claim, index) => index === 0
        ? { ...claim, approved_safe_claim: "Mutated after approval." }
        : claim),
    };
    expect(() => verifyApprovalLock(
      "run.approval",
      result.approval_lock,
      evidence,
      reviews,
      mutatedClaims,
      reviewedOptions,
    )).toThrow("do not exactly equal");

    const fabricatedReviewer = {
      ...reviews,
      decisions: reviews.decisions.map((decision, index) => index === 0
        ? { ...decision, reviewer_id: "reviewer.fabricated" }
        : decision),
    };
    expect(() => verifyApprovalLock(
      "run.approval",
      result.approval_lock,
      evidence,
      fabricatedReviewer,
      result.approved_claims,
      reviewedOptions,
    )).toThrow("digest does not match");
  });
});

describe("provenance closure", () => {
  test("closes every approved origin and preserves final approved text exactly", () => {
    const evidence = evidenceInput();
    const reviews = { schema_version: 1, decisions: [] };
    const approved = approveClaims(evidence, reviews);
    expect(assertProvenanceClosure(approved, evidence, reviews)).toMatchObject({ closed: true, missing: [] });
    const provenance = buildApprovedClaimsProvenance(approved, evidence, reviews);
    expect(provenance).toHaveLength(1);
    expect(provenance[0]).toMatchObject({
      claim_id: "claim.evidence.queue",
      evidence_ids: ["evidence.queue"],
      rendered_claim: EXACT_QUOTE,
    });
  });

  test("reports and rejects missing origins rather than silently dropping claims", () => {
    const evidence = evidenceInput();
    const approved = approveClaims(evidence, { schema_version: 1, decisions: [] });
    const broken = {
      ...approved,
      claims: approved.claims.map((claim, index) => index === 0
        ? { ...claim, origin_evidence_ids: ["evidence.missing"] }
        : claim),
    };
    expect(checkProvenanceClosure(broken, evidence)).toMatchObject({
      closed: false,
      missing: ["evidence.missing"],
      missing_origin_evidence_ids: ["evidence.missing"],
    });
    expect(() => assertProvenanceClosure(broken, evidence)).toThrow("provenance is not closed");
  });
});
