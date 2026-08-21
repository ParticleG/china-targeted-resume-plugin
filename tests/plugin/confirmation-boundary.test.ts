import { afterEach, describe, expect, test } from "bun:test";
import { chmod, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import {
  canonicalJsonSha256,
  validateConfirmationReceipt,
  type ConfirmationReceipt,
  type ConfirmationRequest,
} from "../../src/kernel/approval.ts";
import { ResumePluginRuntime } from "../../src/plugin/runtime.ts";
import { registerResumeTools } from "../../src/plugin/tools/index.ts";

interface FakeSchema {
  min(value: number): FakeSchema;
  max(value: number): FakeSchema;
  int(): FakeSchema;
  positive(): FakeSchema;
  regex(value: RegExp): FakeSchema;
  optional(): FakeSchema;
  describe(value: string): FakeSchema;
  strict(): FakeSchema;
}

interface CapturedTool {
  readonly name: string;
  readonly execute: (...args: unknown[]) => Promise<unknown>;
}

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

function fakeSchema(): FakeSchema {
  const schema: FakeSchema = {
    min: () => schema,
    max: () => schema,
    int: () => schema,
    positive: () => schema,
    regex: () => schema,
    optional: () => schema,
    describe: () => schema,
    strict: () => schema,
  };
  return schema;
}

function captureTools(): { api: ExtensionAPI; tools: CapturedTool[] } {
  const tools: CapturedTool[] = [];
  const zod = {
    string: fakeSchema,
    number: fakeSchema,
    boolean: fakeSchema,
    unknown: fakeSchema,
    enum: (_values: readonly string[]) => fakeSchema(),
    object: (_shape: Readonly<Record<string, unknown>>) => fakeSchema(),
    record: (_key: FakeSchema, _value: FakeSchema) => fakeSchema(),
  };
  return {
    tools,
    api: {
      zod,
      registerTool(tool: CapturedTool) {
        tools.push(tool);
      },
      appendEntry() {},
    } as unknown as ExtensionAPI,
  };
}

function request(runId: string, digestCharacter: string): ConfirmationRequest {
  return {
    schema_version: 1,
    run_id: runId,
    evidence_id: "evidence.p2",
    claim_digest: `sha256:${digestCharacter.repeat(64)}` as `sha256:${string}`,
    disclosure_audience: "hiring_team",
    disclosure_purpose: "targeted_application",
    output_mode: "targeted_application",
    reason_codes: ["p2_disclosure"],
  };
}

function receipt(value: ConfirmationRequest): ConfirmationReceipt {
  return {
    ...value,
    confirmed: true,
    confirmed_by: "interactive_user",
    confirmed_at: "2026-08-21T00:00:00.000Z",
    nonce: "nonce-confirmation-test",
  };
}

describe("interactive confirmation receipts", () => {
  test("rejects cross-run receipts and exact-claim hash mismatches", () => {
    const first = new ResumePluginRuntime("run-first");
    const second = new ResumePluginRuntime("run-second");
    const firstRequest = request("run-first", "a");
    const firstReceipt = receipt(firstRequest);

    first.recordConfirmationReceipt(firstReceipt, "run-first");
    expect(() => second.recordConfirmationReceipt(firstReceipt, "run-second")).toThrow("active run");
    expect(() => validateConfirmationReceipt(request("run-first", "b"), firstReceipt)).toThrow("does not match");
  });

  test("declined UI confirmation never mints a receipt or approval lock", async () => {
    const root = await mkdtemp(join(tmpdir(), "ctr-confirmation-"));
    temporaryDirectories.push(root);
    await chmod(root, 0o700);
    await mkdir(join(root, "sources"), { mode: 0o700 });
    const sourceText = await Bun.file(
      join(import.meta.dir, "../golden/sources/record.md"),
    ).text();
    await writeFile(join(root, "sources", "record.md"), sourceText, { mode: 0o600 });
    await chmod(join(root, "sources", "record.md"), 0o600);

    const golden = JSON.parse(await Bun.file(join(import.meta.dir, "../golden/approval-cases.json")).text()) as {
      cases: Array<{ case_id: string; evidence: Record<string, unknown>; reviews: Record<string, unknown>; options: { approved_safe_claims: Record<string, string> } }>;
    };
    const fixture = golden.cases.find((item) => item.case_id === "p2-extractive-confirmed")!;
    const sourceMap = { schema_version: 1, documents: [], sections: [], blocks: [], proposals: [] };
    const runtime = new ResumePluginRuntime("run-decline");
    const sessionPath = join(root, "session.jsonl");
    await writeFile(sessionPath, "", { mode: 0o600 });
    await chmod(sessionPath, 0o600);
    const uid = typeof process.getuid === "function" ? process.getuid() : 0;
    runtime.authorizeReviewedSemantic("run-decline", {
      provider: "review-provider",
      model: "review-model",
      locality: "local",
      authorizationId: "auth-decline",
      consumerIdentities: {
        "privacy-reviewer": {
          provider: "review-provider",
          model: "review-model",
          locality: "local",
        },
      },
      categories: ["evidence"],
      minimumSlices: [{
        path: "sources/record.md",
        startLine: 3,
        endLine: 3,
        category: "evidence",
        consumer: "privacy-reviewer",
        purpose: "claim-review",
      }],
      sessionJsonlPath: sessionPath,
      observedSession: {
        path: sessionPath,
        mode: 0o600,
        ownerUid: uid,
        expectedOwnerUid: uid,
        isRegularFile: true,
      },
      sessionDirectory: {
        path: root,
        mode: 0o700,
        ownerUid: uid,
        expectedOwnerUid: uid,
        isDirectory: true,
      },
      retention: { strategy: "retain", cleanupSupported: false },
    });
    const evidenceDigest = canonicalJsonSha256(fixture.evidence);
    const evidenceReceipt = {
      runId: "run-decline",
      inputId: "evidence-input.p2",
      digest: evidenceDigest,
      sourceMapDigest: canonicalJsonSha256(sourceMap),
      candidateCount: 1,
      proposalCount: 0,
      unresolvedQuestionCount: 0,
      nonCandidateOwnerCount: 0,
      requiresReviewedSemantic: true,
    } as const;
    runtime.recordEvidenceValidation(evidenceReceipt, "run-decline");
    runtime.recordEvidenceBundle(evidenceReceipt, {
      sourceMap,
      evidenceInput: fixture.evidence,
    }, "run-decline");

    const captured = captureTools();
    registerResumeTools(captured.api, runtime);
    const lockTool = captured.tools.find((tool) => tool.name === "resume_lock_approved_claims")!;
    const context = {
      hasUI: true,
      ui: {
        async confirm() {
          return false;
        },
      },
    } as unknown as ExtensionContext;
    const rawResult = await lockTool.execute(
      "lock-declined",
      {
        runId: "run-decline",
        sourceRoot: root,
        evidenceReceiptDigest: evidenceDigest,
        payload: {
          review_decisions: (fixture.reviews.decisions as unknown[]).map((decision) => ({
            contract_version: 1,
            agent_role: "privacy-reviewer",
            mode: "reviewed_semantic",
            authorization_id: "auth-decline",
            claim_id: "claim.evidence.p2",
            effective_fact_policy: "F2",
            effective_disclosure_policy: "P2",
            prefilter_status: "passed",
            permission_status: "confirmed",
            request_output_mode: "targeted_application",
            redactions: [],
            blocking_reasons: [],
            decision,
          })),
          approved_safe_claims: fixture.options.approved_safe_claims,
          output_mode: "targeted_application",
        },
      },
      undefined,
      undefined,
      context,
    ) as { content: Array<{ text: string }>; isError?: boolean };

    expect(rawResult.isError).toBe(true);
    expect(JSON.parse(rawResult.content[0]!.text)).toMatchObject({
      error: { code: "CONFIRMATION_DECLINED" },
    });
    expect(runtime.confirmationReceipts("run-decline")).toEqual([]);
    expect(runtime.status("run-decline").approval).toBeUndefined();
  });

  test("metadata-only lock rejects nonempty canonical review decisions", async () => {
    const runtime = new ResumePluginRuntime("run-metadata-reviews");
    const evidence = {
      schema_version: 1,
      input_id: "evidence.metadata",
      domain: "evidence",
      candidates: [],
      unresolved_questions: [],
    };
    const sourceMap = { schema_version: 1, documents: [], sections: [], blocks: [], proposals: [] };
    const digest = canonicalJsonSha256(evidence);
    const receipt = {
      runId: "run-metadata-reviews",
      inputId: "evidence.metadata",
      digest,
      sourceMapDigest: canonicalJsonSha256(sourceMap),
      candidateCount: 0,
      proposalCount: 0,
      unresolvedQuestionCount: 0,
      nonCandidateOwnerCount: 0,
      requiresReviewedSemantic: false,
    } as const;
    runtime.recordEvidenceValidation(receipt);
    runtime.recordEvidenceBundle(receipt, { sourceMap, evidenceInput: evidence });
    const captured = captureTools();
    registerResumeTools(captured.api, runtime);
    const lockTool = captured.tools.find((tool) => tool.name === "resume_lock_approved_claims")!;
    const rawResult = await lockTool.execute(
      "lock-metadata-review",
      {
        runId: "run-metadata-reviews",
        sourceRoot: "/unread",
        evidenceReceiptDigest: digest,
        payload: {
          review_decisions: {
            schema_version: 1,
            decisions: [{
              review_id: "forged.raw",
              evidence_id: "forged",
              reviewer_id: "forged",
              review_kind: "privacy",
              outcome: "approve",
              reasoning: "forged",
              contribution_qualifiers: [],
              metric_qualifiers: [],
              disclosure_decision: "allowed",
              disclosure_audience: "hiring_team",
              disclosure_purpose: "targeted_application",
              user_confirmation_required: false,
              user_confirmed: false,
              questions: [],
            }],
          },
          approved_safe_claims: {},
          output_mode: "targeted_application",
        },
      },
      undefined,
      undefined,
      { hasUI: true, ui: { async confirm() { return true; } } } as unknown as ExtensionContext,
    ) as { content: Array<{ text: string }>; isError?: boolean };
    expect(rawResult.isError).toBe(true);
    expect(JSON.parse(rawResult.content[0]!.text)).toMatchObject({
      error: { code: "KERNEL_VALIDATION_FAILED" },
    });
  });
});
