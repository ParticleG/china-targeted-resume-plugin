import { describe, expect, test } from "bun:test";
import {
  ResumePluginRuntime,
  SourcePolicyStateError,
  type SourcePolicyIndex,
} from "../../src/plugin/runtime.ts";

const SOURCE_HASH = `sha256:${"a".repeat(64)}` as const;
const MAP_DIGEST = `sha256:${"b".repeat(64)}` as const;

function index(blockedAncestor: boolean): SourcePolicyIndex {
  return {
    runId: "run-policy",
    digest: MAP_DIGEST,
    spans: [
      {
        path: "records/evidence.md",
        kind: "section",
        sourceHash: SOURCE_HASH,
        startLine: 1,
        endLine: 20,
        effectivePolicy: blockedAncestor ? "F2/P3" : "F2/P1",
        ancestorPolicies: blockedAncestor ? ["F2", "P3"] : ["F2", "P1"],
        headingAncestry: blockedAncestor ? ["P3 Internal", "Evidence"] : ["Evidence"],
        blockedByPolicy: blockedAncestor,
      },
      {
        path: "records/evidence.md",
        kind: "block",
        sourceHash: SOURCE_HASH,
        startLine: 5,
        endLine: 6,
        effectivePolicy: "F2/P1",
        ancestorPolicies: ["F2", "P1"],
        headingAncestry: ["Evidence"],
        blockedByPolicy: false,
      },
    ],
  };
}

describe("parser-authoritative source policy receipts", () => {
  test("rejects a safe-looking child block under an inherited P3 section", () => {
    const runtime = new ResumePluginRuntime("run-policy");
    runtime.recordSourcePolicyIndex(index(true));

    expect(() => runtime.sourcePolicyForSlice(
      "records/evidence.md",
      5,
      6,
      MAP_DIGEST,
      "run-policy",
    )).toThrow(SourcePolicyStateError);
    try {
      runtime.sourcePolicyForSlice("records/evidence.md", 5, 6, MAP_DIGEST, "run-policy");
    } catch (error) {
      expect(error).toMatchObject({ code: "SOURCE_POLICY_FORBIDDEN" });
    }
  });

  test("sections provide deny ancestry but never authorize omitted or partial block lines", () => {
    const runtime = new ResumePluginRuntime("run-policy");
    runtime.recordSourcePolicyIndex(index(false));

    expect(() => runtime.sourcePolicyForSlice(
      "records/evidence.md",
      7,
      7,
      MAP_DIGEST,
      "run-policy",
    )).toThrow("not fully owned");
    expect(() => runtime.sourcePolicyForSlice(
      "records/evidence.md",
      5,
      7,
      MAP_DIGEST,
      "run-policy",
    )).toThrow("not fully owned");
  });

  test("rejects stale source-map receipt digests", () => {
    const runtime = new ResumePluginRuntime("run-policy");
    runtime.recordSourcePolicyIndex(index(false));

    expect(() => runtime.sourcePolicyForSlice(
      "records/evidence.md",
      5,
      6,
      `sha256:${"c".repeat(64)}`,
      "run-policy",
    )).toThrow("receipt does not match");
  });
});
