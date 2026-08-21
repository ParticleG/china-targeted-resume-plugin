import { describe, expect, test } from "bun:test";
import type { ApprovalReceipt, EvidenceValidationReceipt } from "../../src/plugin/runtime.ts";
import { ResumePluginRuntime } from "../../src/plugin/runtime.ts";

const hash = (character: string) => `sha256:${character.repeat(64)}` as `sha256:${string}`;

function evidenceReceipt(character: string): EvidenceValidationReceipt {
  return {
    runId: "run-receipts",
    inputId: `evidence-${character}`,
    digest: hash(character),
    sourceMapDigest: hash(character === "a" ? "c" : "d"),
    candidateCount: 1,
    proposalCount: 1,
    unresolvedQuestionCount: 0,
    nonCandidateOwnerCount: 0,
    requiresReviewedSemantic: false,
  };
}

function approvalReceipt(character: string): ApprovalReceipt {
  return {
    backend: "typescript",
    runId: "run-receipts",
    digest: hash(character),
    evidenceInputId: `evidence-${character}`,
    evidenceIds: [`evidence.${character}`],
    reviewDecisionIds: [],
    claimIds: [`claim.${character}`],
    reviewerCount: 0,
  };
}

describe("private receipt-keyed runtime handoff", () => {
  test("a later validation cannot silently replace an earlier receipt bundle", () => {
    const runtime = new ResumePluginRuntime("run-receipts");
    const first = evidenceReceipt("a");
    const second = evidenceReceipt("b");
    runtime.recordEvidenceValidation(first);
    runtime.recordEvidenceBundle(first, {
      sourceMap: { private: "FIRST-PRIVATE-SENTINEL" },
      evidenceInput: { private: "FIRST-EVIDENCE-SENTINEL" },
    });
    runtime.recordEvidenceValidation(second);
    runtime.recordEvidenceBundle(second, {
      sourceMap: { private: "SECOND-PRIVATE-SENTINEL" },
      evidenceInput: { private: "SECOND-EVIDENCE-SENTINEL" },
    });

    expect(runtime.evidenceBundle(first.digest).evidenceInput).toEqual({
      private: "FIRST-EVIDENCE-SENTINEL",
    });
    expect(runtime.evidenceBundle(second.digest).evidenceInput).toEqual({
      private: "SECOND-EVIDENCE-SENTINEL",
    });
    expect(JSON.stringify(runtime.status())).not.toContain("PRIVATE-SENTINEL");
    expect(JSON.stringify(runtime.status())).not.toContain("EVIDENCE-SENTINEL");
  });

  test("approved claim text remains private and approval bundles resolve by exact digest", () => {
    const runtime = new ResumePluginRuntime("run-receipts");
    const first = approvalReceipt("e");
    const second = approvalReceipt("f");
    runtime.recordApprovalReceipt(first);
    runtime.recordApprovalBundle(first, {
      approvedClaims: { claims: [{ approved_safe_claim: "FIRST-CLAIM-SENTINEL" }] },
      approvalLock: { digest: first.digest },
      reviews: { private: "FIRST-REVIEW-SENTINEL" },
      approvedSafeClaims: {},
      outputMode: "targeted_application",
      evidenceReceiptDigest: hash("a"),
      confirmationReceipts: [],
    });
    runtime.recordApprovalReceipt(second);
    runtime.recordApprovalBundle(second, {
      approvedClaims: { claims: [{ approved_safe_claim: "SECOND-CLAIM-SENTINEL" }] },
      approvalLock: { digest: second.digest },
      reviews: { private: "SECOND-REVIEW-SENTINEL" },
      approvedSafeClaims: {},
      outputMode: "targeted_application",
      evidenceReceiptDigest: hash("b"),
      confirmationReceipts: [],
    });

    expect(runtime.approvalBundle(first.digest).approvedClaims).toEqual({
      claims: [{ approved_safe_claim: "FIRST-CLAIM-SENTINEL" }],
    });
    expect(runtime.approvalBundle(second.digest).approvedClaims).toEqual({
      claims: [{ approved_safe_claim: "SECOND-CLAIM-SENTINEL" }],
    });
    expect(JSON.stringify(runtime.status())).not.toContain("CLAIM-SENTINEL");
    expect(JSON.stringify(runtime.status())).not.toContain("REVIEW-SENTINEL");
  });
});
