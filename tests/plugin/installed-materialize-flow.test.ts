import { afterEach, describe, expect, test } from "bun:test";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { ResumePluginRuntime } from "../../src/plugin/runtime.ts";
import {
  PythonKernelBridge,
  registerResumeTools,
  type JsonObject,
  type KernelRequest,
} from "../../src/plugin/tools/index.ts";
import type { KernelRunOptions } from "../../src/plugin/tools/python-bridge.ts";

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

function captureTools(entries: unknown[]): { api: ExtensionAPI; tools: CapturedTool[] } {
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
      appendEntry(_type: string, data: unknown) {
        entries.push(data);
      },
    } as unknown as ExtensionAPI,
  };
}

function resultEnvelope(value: unknown): { ok: boolean; data?: Record<string, unknown>; error?: Record<string, unknown> } {
  const result = value as { content: Array<{ text: string }> };
  return JSON.parse(result.content[0]!.text) as { ok: boolean; data?: Record<string, unknown>; error?: Record<string, unknown> };
}

class MaterializeBridge extends PythonKernelBridge {
  readonly #real = new PythonKernelBridge();
  composeCalls = 0;

  override async run(request: KernelRequest, options: KernelRunOptions = {}): Promise<JsonObject> {
    if (request.operation === "generate-from-ir") {
      this.composeCalls += 1;
      return { operation: "generate-from-ir", run_dir: "/private/fake-run", artifacts: [], summary: {} };
    }
    return this.#real.run(request, options);
  }
}

describe("installed metadata-only materialization handoff", () => {
  test("materializes privately and routes unresolved ownership to reviewed semantics", async () => {
    const sourceRoot = await mkdtemp(join(tmpdir(), "ctr-installed-source-"));
    temporaryDirectories.push(sourceRoot);
    await chmod(sourceRoot, 0o700);
    const sentinel = "MATERIALIZE-PRIVATE-SENTINEL";
    const sourceText = `Fact state: F2\nDisclosure level: P1\n\n# Evidence\n\n- ${sentinel} operated a queue worker.\n`;
    const sourcePath = join(sourceRoot, "evidence.md");
    await writeFile(sourcePath, sourceText, { mode: 0o600 });
    await chmod(sourcePath, 0o600);

    const entries: unknown[] = [];
    const captured = captureTools(entries);
    const runtime = new ResumePluginRuntime("run-installed");
    const bridge = new MaterializeBridge();
    registerResumeTools(captured.api, runtime, { bridge });
    const context = { hasUI: true, ui: { async confirm() { return true; } } } as unknown as ExtensionContext;
    const tool = (name: string) => captured.tools.find((candidate) => candidate.name === name)!;

    const discovered = resultEnvelope(await tool("resume_discover_structure").execute(
      "discover",
      { runId: "run-installed", sourceRoot },
      undefined,
      undefined,
      context,
    ));
    expect(discovered.ok).toBe(true);
    const sourceMap = discovered.data!.source_map as Record<string, unknown>;
    const blocks = sourceMap.blocks as Array<Record<string, unknown>>;
    const selected = blocks.find((block) => {
      const flags = block.structural_flags as Record<string, unknown> | undefined;
      return flags?.effective_fact_policy === "F2" && flags?.effective_disclosure_policy === "P1";
    })!;
    const blockId = selected.block_id as string;

    const validatedMap = resultEnvelope(await tool("resume_validate_source_map").execute(
      "validate-map",
      { runId: "run-installed", sourceRoot, sourceMap },
      undefined,
      undefined,
      context,
    ));
    expect(validatedMap).toMatchObject({ ok: true });
    const mapReceipt = validatedMap.data!.source_map_receipt as Record<string, unknown>;
    const sourceMapDigest = mapReceipt.digest as string;

    const validatedEvidenceRaw = await tool("resume_validate_evidence_ir").execute(
      "materialize",
      {
        runId: "run-installed",
        sourceRoot,
        sourceMapDigest,
        payload: {
          materialize_extractive: {
            input_id: "evidence.installed",
            selected_block_ids: [blockId],
            evidence_ids: { [blockId]: "evidence.installed.queue" },
            requirement_ids: [],
            profile_field_marker: "evidence",
          },
        },
      },
      undefined,
      undefined,
      context,
    );
    const validatedEvidence = resultEnvelope(validatedEvidenceRaw);
    expect(validatedEvidence).toMatchObject({ ok: true });
    expect(JSON.stringify(validatedEvidenceRaw)).not.toContain(sentinel);
    expect(JSON.stringify(entries)).not.toContain(sentinel);
    const evidenceReceipt = validatedEvidence.data!.evidence_receipt as Record<string, unknown>;
    expect(evidenceReceipt).toMatchObject({
      nonCandidateOwnerCount: 1,
      requiresReviewedSemantic: true,
    });
    const evidenceReceiptDigest = evidenceReceipt.digest as string;

    const lockedRaw = await tool("resume_lock_approved_claims").execute(
      "lock",
      {
        runId: "run-installed",
        sourceRoot,
        evidenceReceiptDigest,
        payload: {
          review_decisions: { schema_version: 1, decisions: [] },
          approved_safe_claims: {},
          output_mode: "targeted_application",
        },
      },
      undefined,
      undefined,
      context,
    );
    const locked = resultEnvelope(lockedRaw);
    expect(locked).toMatchObject({
      ok: false,
      error: { code: "KERNEL_VALIDATION_FAILED" },
    });
    expect(JSON.stringify(lockedRaw)).not.toContain(sentinel);
    expect(JSON.stringify(entries)).not.toContain(sentinel);
    expect(bridge.composeCalls).toBe(0);
  });
});
