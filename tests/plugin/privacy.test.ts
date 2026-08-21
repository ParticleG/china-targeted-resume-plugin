import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import {
  auditSessionJsonl,
  authorizeReviewedSemantic,
  canReadSourceSlice,
  createRunPrivacyState,
  disclosureFor,
  prefilterSourceSlice,
  readAuthorizedSourceSlice,
  reportSessionCleanup,
  summarizePrivacyState,
  type RunPrivacyState,
  type SessionCleanupResult,
  type SourceSliceRequest,
} from "../../src/plugin/privacy";

const uid = (): number => {
  const candidate = (process as typeof process & { getuid?: () => number }).getuid;
  return candidate ? candidate() : 0;
};

let temporaryRoot = "";

beforeEach(() => {
  temporaryRoot = mkdtempSync(join("/tmp", "china-resume-privacy-"));
});

afterEach(() => {
  if (temporaryRoot) rmSync(temporaryRoot, { recursive: true, force: true });
  temporaryRoot = "";
});

function sessionPath(): string {
  const path = join(temporaryRoot, "omp-session.jsonl");
  writeFileSync(path, "", { mode: 0o600 });
  chmodSync(path, 0o600);
  return path;
}

function grant(
  state: RunPrivacyState,
  path: string,
  extra: {
    readonly observedSession?: NonNullable<Parameters<typeof authorizeReviewedSemantic>[1]["observedSession"]>;
    readonly sessionDirectory?: NonNullable<Parameters<typeof authorizeReviewedSemantic>[1]["sessionDirectory"]>;
  } = {},
): RunPrivacyState {
  return authorizeReviewedSemantic(state, {
    provider: "controlled-provider",
    model: "local-review-model",
    locality: "local",
    authorizationId: "test-auth",
    consumerIdentities: {
      main: { provider: "controlled-provider", model: "local-review-model", locality: "local" },
      "source-mapper": { provider: "controlled-provider", model: "local-review-model", locality: "local" },
      "role-analyst": { provider: "controlled-provider", model: "local-review-model", locality: "local" },
      "requirement-reviewer": { provider: "controlled-provider", model: "local-review-model", locality: "local" },
      "evidence-reviewer": { provider: "controlled-provider", model: "local-review-model", locality: "local" },
      "contribution-reviewer": { provider: "controlled-provider", model: "local-review-model", locality: "local" },
      "privacy-reviewer": { provider: "controlled-provider", model: "local-review-model", locality: "local" },
    },
    categories: ["evidence", "jd-company"],
    minimumSlices: [
      {
        path: "projects/harbor-ledger.md",
        startLine: 1,
        endLine: 12,
        category: "evidence",
        consumers: ["main", "source-mapper", "requirement-reviewer", "evidence-reviewer", "contribution-reviewer", "privacy-reviewer"],
        purpose: "claim-review",
      },
      {
        path: "roles/acme.md",
        startLine: 2,
        endLine: 8,
        category: "jd-company",
        consumers: ["main", "source-mapper", "role-analyst", "requirement-reviewer"],
        purpose: "role-analysis",
      },
    ],
    sessionJsonlPath: path,
    observedSession: {
      path,
      mode: 0o600,
      ownerUid: uid(),
      expectedOwnerUid: uid(),
      isRegularFile: true,
    },
    sessionDirectory: {
      path: dirname(path),
      mode: 0o700,
      ownerUid: uid(),
      expectedOwnerUid: uid(),
      isDirectory: true,
    },
    retention: { strategy: "retain-until-expiry", maxAgeSeconds: 3600, cleanupSupported: false },
    ...extra,
  });
}

const request = (overrides: Partial<SourceSliceRequest> = {}): SourceSliceRequest => ({
  authorizationId: "test-auth",
  provider: "controlled-provider",
  model: "local-review-model",
  locality: "local",
  consumer: "evidence-reviewer",
  path: "projects/harbor-ledger.md",
  startLine: 2,
  endLine: 5,
  category: "evidence",
  purpose: "claim-review",
  ...overrides,
});

describe("run-local privacy state", () => {
  test("metadata-only is an immutable default for every matrix consumer", () => {
    const state = createRunPrivacyState({ runId: "run-default", startedAt: "2026-08-21T00:00:00.000Z" });
    const consumers = ["main", "source-mapper", "role-analyst", "requirement-reviewer", "evidence-reviewer", "contribution-reviewer", "privacy-reviewer", "resume-advisor"] as const;
    for (const consumer of consumers) {
      const policy = disclosureFor(state, consumer);
      expect(policy.mode).toBe("metadata-only");
      expect(policy.rawSourceAllowed).toBe(false);
      expect(prefilterSourceSlice(state, request({ consumer, content: "safe source" })).ok).toBe(false);
    }
    expect(state.mode).toBe("metadata-only");
    expect(state.authorization).toBeUndefined();
  });

  test("explicit authorization records provider, locality, exact categories, slices, session checks, and retention", () => {
    const path = sessionPath();
    const state = createRunPrivacyState({ runId: "run-authorized", startedAt: "2026-08-21T00:00:00.000Z" });
    const reviewed = grant(state, path);
    expect(reviewed).not.toBe(state);
    expect(reviewed.mode).toBe("reviewed-semantic");
    expect(reviewed.authorization?.authorizationId).toBe("test-auth");
    expect(reviewed.authorization?.provider).toBe("controlled-provider");
    expect(reviewed.authorization?.model).toBe("local-review-model");
    expect(reviewed.authorization?.locality).toBe("local");
    expect(reviewed.authorization?.localVsRemote).toBe("local");
    expect(reviewed.authorization?.categories).toEqual(["evidence", "jd-company"]);
    expect(reviewed.authorization?.minimumSlices).toHaveLength(2);
    expect(reviewed.authorization?.minimumSlices[0]?.purpose).toBe("claim-review");
    expect(reviewed.authorization?.minimumSlices[0]?.consumers).toContain("evidence-reviewer");
    expect(reviewed.authorization?.sessionJsonlPath).toBe(path);
    expect(reviewed.authorization?.sessionObservation.privatePermissions).toBe(true);
    expect(reviewed.authorization?.sessionObservation.ownerMatches).toBe(true);
    expect(reviewed.authorization?.retention.cleanupSupported).toBe(false);
    expect(reviewed.authorization?.retention.deletionGuarantee).toBe("not-guaranteed");
    expect(reviewed.authorization?.runId).toBe("run-authorized");
    const summary = summarizePrivacyState(reviewed);
    expect(summary.authorization.present).toBe(true);
    expect(summary.authorizationId).toBe("test-auth");
    expect(summary.authorization.minimumSliceCount).toBe(2);
    expect(summary.retention.deletionGuarantee).toBe("not-guaranteed");
  });

  test("authorization rejects forbidden categories and source-bearing metadata", () => {
    const state = createRunPrivacyState({ runId: "run-reject" });
    const path = sessionPath();
    expect(() =>
      authorizeReviewedSemantic(state, {
        provider: "provider",
        model: "model",
        locality: "remote",
        categories: ["contacts"],
        minimumSlices: ["projects/harbor-ledger.md#L1-L2"],
        sessionJsonlPath: path,
        observedSession: { path, mode: 0o600, ownerUid: uid(), expectedOwnerUid: uid() },
        retention: { strategy: "retain", cleanupSupported: false },
      }),
    ).toThrow();
    expect(() =>
      authorizeReviewedSemantic(state, {
        provider: "provider",
        model: "model",
        locality: "local",
        categories: ["evidence"],
        minimumSlices: [{ path: "projects/harbor-ledger.md", category: "evidence" }],
        sessionJsonlPath: path,
        observedSession: { path, mode: 0o600, ownerUid: uid(), expectedOwnerUid: uid() },
        retention: { strategy: "retain", cleanupSupported: false },
        ...( { content: "private source body" } as unknown as Record<string, unknown>),
      } as never),
    ).toThrow();
  });

  test("authorization requires private session permissions and owner match", () => {
    const path = sessionPath();
    const state = createRunPrivacyState({ runId: "run-permission" });
    expect(() => grant(state, path, {
      observedSession: { path, mode: 0o640, ownerUid: uid(), expectedOwnerUid: uid() },
    })).toThrow();
    expect(() => grant(state, path, {
      observedSession: { path, mode: 0o600, ownerUid: uid() + 1, expectedOwnerUid: uid() },
    })).toThrow();
  });
});

describe("deterministic source prefilter", () => {
  test("allows only an authorized minimum range and rejects unrelated or broad slices", () => {
    const reviewed = grant(createRunPrivacyState({ runId: "run-scope" }), sessionPath());
    expect(prefilterSourceSlice(reviewed, request()).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ startLine: 1, endLine: 12 })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ startLine: 1, endLine: 13 })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ path: "projects/other.md" })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ wholeRepository: true, path: "projects/harbor-ledger.md" })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ path: "projects" })).ok).toBe(false);
  });
  test("enforces reviewed-semantic consumer matrix and advisor raw denial", () => {
    const reviewed = grant(createRunPrivacyState({ runId: "run-matrix" }), sessionPath());
    expect(prefilterSourceSlice(reviewed, request({ consumer: "main" })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "source-mapper" })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "role-analyst", path: "roles/acme.md", startLine: 2, endLine: 8, category: "jd-company", purpose: "role-analysis" })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "evidence-reviewer" })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "requirement-reviewer", path: "roles/acme.md", startLine: 2, endLine: 8, category: "jd-company", purpose: "role-analysis" })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "contribution-reviewer" })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "privacy-reviewer" })).ok).toBe(true);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "resume-advisor" })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ consumer: "role-analyst" })).ok).toBe(false);
  });

  test("rejects contact, credential, secret-looking, F6/P3, and oversize requests before return", () => {
    const reviewed = grant(createRunPrivacyState({ runId: "run-forbidden" }), sessionPath());
    expect(prefilterSourceSlice(reviewed, request({ path: "contacts.md" })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ path: "projects/api-keys.md" })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ content: "F6/P3 restricted text" })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ content: "person@example.invalid" })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ bytes: 17 * 1024 })).ok).toBe(false);
    expect(prefilterSourceSlice(reviewed, request({ effectivePolicy: "F2 inherited F6", ancestorPolicies: ["F1/P0", "F6/P3"] })).ok).toBe(false);
  });

  test("never invokes the source reader when metadata-only or path policy denies", async () => {
    const state = createRunPrivacyState({ runId: "run-reader" });
    let reads = 0;
    const reader = () => {
      reads += 1;
      return "private source";
    };
    const denied = await readAuthorizedSourceSlice(state, request(), reader);
    expect(denied.ok).toBe(false);
    expect(reads).toBe(0);
    const reviewed = grant(state, sessionPath());
    const deniedPath = await readAuthorizedSourceSlice(reviewed, request({ path: "credentials.md" }), reader);
    expect(deniedPath.ok).toBe(false);
    expect(reads).toBe(0);
  });

  test("returns only an authorized, prefiltered source body", async () => {
    const reviewed = grant(createRunPrivacyState({ runId: "run-read" }), sessionPath());
    const result = await readAuthorizedSourceSlice(reviewed, request(), async () => "safe source slice");
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.content).toBe("safe source slice");
    expect(canReadSourceSlice(reviewed, request())).toBe(true);
    expect(canReadSourceSlice(reviewed, request({ consumer: "resume-advisor" }))).toBe(false);
  });
});

describe("OMP-owned session JSONL audit", () => {
  test("checks private mode, authorized slice scope, and absence of forbidden sentinels", () => {
    const path = sessionPath();
    const state = grant(createRunPrivacyState({ runId: "run-audit" }), path);
    writeFileSync(path, JSON.stringify({ sourceSlice: { authorizationId: "test-auth", provider: "controlled-provider", model: "local-review-model", locality: "local", consumer: "evidence-reviewer", purpose: "claim-review", path: "projects/harbor-ledger.md", startLine: 2, endLine: 5, category: "evidence", content: "safe source" } }) + "\n");
    const report = auditSessionJsonl(state);
    expect(report.ok).toBe(true);
    expect(report.privatePermissions).toBe(true);
    expect(report.ownerMatches).toBe(true);
    expect(report.disclosedSliceCount).toBe(1);
    expect(report.outOfScopeSliceCount).toBe(0);
    expect(report.forbiddenSentinelCount).toBe(0);
    expect(report.retainedArtifact).toBe(true);
    expect(report.deletionClaimed).toBe(false);
  });

  test("parses the actual OMP xdev tool-result envelope without treating all messages as slices", () => {
    const path = sessionPath();
    const state = grant(createRunPrivacyState({ runId: "run-audit-xdev" }), path);
    const envelope = {
      ok: true,
      tool: "resume_read_source_slice",
      runId: "run-audit-xdev",
      data: {
        ok: true,
        authorizationId: "test-auth",
        provider: "controlled-provider",
        model: "local-review-model",
        locality: "local",
        consumer: "evidence-reviewer",
        purpose: "claim-review",
        path: "projects/harbor-ledger.md",
        startLine: 2,
        endLine: 5,
        category: "evidence",
        content: "safe source",
      },
    };
    writeFileSync(path, [
      JSON.stringify({
        type: "message",
        message: {
          role: "toolResult",
          toolName: "write",
          content: [{ type: "text", text: JSON.stringify(envelope) }],
        },
      }),
      JSON.stringify({
        type: "message",
        message: {
          role: "assistant",
          content: [{ type: "text", text: "Ordinary policy discussion is not a disclosed source slice." }],
        },
      }),
    ].join("\n"));
    const report = auditSessionJsonl(state);
    expect(report.ok).toBe(true);
    expect(report.disclosedSliceCount).toBe(1);
    expect(report.outOfScopeSliceCount).toBe(0);
    expect(report.forbiddenSentinelCount).toBe(0);
  });

  test("reports out-of-scope and forbidden JSONL content without returning raw lines", () => {
    const path = sessionPath();
    const state = grant(createRunPrivacyState({ runId: "run-audit-reject" }), path);
    writeFileSync(path, [
      JSON.stringify({ sourceSlice: { authorizationId: "test-auth", provider: "controlled-provider", model: "local-review-model", locality: "local", consumer: "evidence-reviewer", purpose: "claim-review", path: "projects/other.md", startLine: 1, endLine: 2, content: "unrelated" } }),
      JSON.stringify({ sourceSlice: { authorizationId: "test-auth", provider: "controlled-provider", model: "local-review-model", locality: "local", consumer: "evidence-reviewer", purpose: "claim-review", path: "projects/harbor-ledger.md", startLine: 2, endLine: 5, content: "F6/P3 restricted" } }),
    ].join("\n"));
    const report = auditSessionJsonl(state);
    expect(report.ok).toBe(false);
    expect(report.outOfScopeSliceCount).toBeGreaterThan(0);
    expect(report.forbiddenSentinelCount).toBeGreaterThan(0);
    expect(JSON.stringify(report)).not.toContain("unrelated");
    expect(JSON.stringify(report)).not.toContain("restricted");
  });

  test("retention reporting never claims deletion when cleanup is unsupported", () => {
    const path = sessionPath();
    const state = grant(createRunPrivacyState({ runId: "run-retention" }), path);
    const cleanup: SessionCleanupResult = { supported: false, attempted: true, deleted: true, verified: true };
    const normalized = reportSessionCleanup(state, cleanup);
    expect(normalized.deleted).toBe(false);
    expect(normalized.verified).toBe(false);
    const report = auditSessionJsonl(state, { cleanup: normalized });
    expect(report.retainedArtifact).toBe(true);
    expect(report.deletionClaimed).toBe(false);
  });

  test("rejects group/world-readable OMP JSONL artifacts", () => {
    const path = sessionPath();
    const state = grant(createRunPrivacyState({ runId: "run-audit-mode" }), path);
    chmodSync(path, 0o644);
    const report = auditSessionJsonl(state, { observation: { path, mode: 0o644, ownerUid: uid(), expectedOwnerUid: uid() } });
    expect(report.privatePermissions).toBe(false);
    expect(report.ok).toBe(false);
  });

  test("requires a private owned session directory during authorization", () => {
    const path = sessionPath();
    const state = createRunPrivacyState({ runId: "run-directory-auth" });
    expect(() => grant(state, path, {
      sessionDirectory: { path: dirname(path), mode: 0o755, ownerUid: uid(), expectedOwnerUid: uid(), isDirectory: true },
    })).toThrow();
  });

  test("audits sibling task/advisor artifacts and reports receipt-proof limitations", () => {
    const path = sessionPath();
    const state = grant(createRunPrivacyState({ runId: "run-tree" }), path);
    const taskPath = join(dirname(path), "task.jsonl");
    const advisorPath = join(dirname(path), "advisor.md");
    writeFileSync(taskPath, JSON.stringify({ type: "task", result: "retained" }));
    writeFileSync(advisorPath, "advisor artifact retained");
    chmodSync(taskPath, 0o644);
    chmodSync(advisorPath, 0o644);
    const report = auditSessionJsonl(state);
    expect(report.tree.jsonlCount).toBeGreaterThanOrEqual(2);
    expect(report.tree.markdownCount).toBeGreaterThanOrEqual(1);
    expect(report.tree.weakDirectoryCount).toBe(0);
    expect(report.tree.weakFileCount).toBeGreaterThanOrEqual(2);
    expect(report.tree.scopeProof).toBe("receipts-incomplete");
    expect(report.effectivePrivacy).toBe("weak-file");
    expect(report.ok).toBe(false);
    expect(JSON.stringify(report)).not.toContain("advisor artifact retained");
    expect(JSON.stringify(report)).not.toContain('"result":"retained"');
  });

  test("rejects a weak nested session artifact directory", () => {
    const path = sessionPath();
    const state = grant(createRunPrivacyState({ runId: "run-tree-weak" }), path);
    const nested = join(dirname(path), "subagent");
    mkdirSync(nested, { mode: 0o755 });
    chmodSync(nested, 0o755);
    const report = auditSessionJsonl(state);
    expect(report.tree.weakDirectoryCount).toBeGreaterThan(0);
    expect(report.effectivePrivacy).toBe("weak-directory");
    expect(report.ok).toBe(false);
  });
});
