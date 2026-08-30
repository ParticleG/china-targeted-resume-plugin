import { afterEach, describe, expect, test } from "bun:test";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type {
  ExtensionAPI,
  ExtensionCommandContext,
} from "@oh-my-pi/pi-coding-agent";
import extension, {
  registerChinaTargetedResumeExtension,
} from "../../src/plugin/extension.ts";
import { RESUME_COMMAND_NAMES } from "../../src/plugin/commands/index.ts";
import { RESUME_TOOL_NAMES } from "../../src/plugin/tools/index.ts";

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

interface CapturedCommand {
  readonly description?: string;
  readonly getArgumentCompletions?: (
    argumentPrefix: string,
  ) => Array<{
    readonly value: string;
    readonly label: string;
    readonly description?: string;
  }> | null;
  readonly handler: (args: string, context: ExtensionCommandContext) => Promise<void>;
}

interface CapturedTool {
  readonly name: string;
  readonly execute: (...args: unknown[]) => Promise<unknown>;
}

interface FakePiCapture {
  readonly api: ExtensionAPI;
  readonly commands: Map<string, CapturedCommand>;
  readonly tools: CapturedTool[];
  readonly prompts: string[];
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

function capturePi(): FakePiCapture {
  const commands = new Map<string, CapturedCommand>();
  const tools: CapturedTool[] = [];
  const prompts: string[] = [];
  const zod = {
    string: fakeSchema,
    number: fakeSchema,
    boolean: fakeSchema,
    unknown: fakeSchema,
    enum: (_values: readonly string[]) => fakeSchema(),
    object: (_shape: Readonly<Record<string, unknown>>) => fakeSchema(),
    record: (_key: FakeSchema, _value: FakeSchema) => fakeSchema(),
  };
  const api = {
    zod,
    registerCommand(name: string, command: CapturedCommand) {
      commands.set(name, command);
    },
    registerTool(tool: CapturedTool) {
      tools.push(tool);
    },
    sendUserMessage(prompt: string) {
      prompts.push(prompt);
    },
  } as unknown as ExtensionAPI;
  return { api, commands, tools, prompts };
}

function commandContext(notifications: string[]): ExtensionCommandContext {
  return {
    hasUI: true,
    model: undefined,
    ui: {
      notify(message: string) {
        notifications.push(message);
      },
    },
  } as unknown as ExtensionCommandContext;
}

describe("OMP Extension registration", () => {
  test("default import registers seven commands and nine tools without launching OMP", () => {
    const captured = capturePi();
    extension(captured.api);

    expect([...captured.commands.keys()]).toEqual([...RESUME_COMMAND_NAMES]);
    expect(captured.tools.map((tool) => tool.name)).toEqual([...RESUME_TOOL_NAMES]);
    expect(captured.tools).toHaveLength(9);
    expect(captured.commands.size).toBe(7);
    expect(captured.prompts).toEqual([]);
    expect(captured.tools.every((tool) => tool.execute.length === 5)).toBe(true);
  });

  test("registration returns isolated metadata-only runtime state", () => {
    const first = registerChinaTargetedResumeExtension(capturePi().api);
    const second = registerChinaTargetedResumeExtension(capturePi().api);

    expect(first).not.toBe(second);
    expect(first.status().privacy.mode).toBe("metadata-only");
    expect(first.status().completedTools).toEqual([]);
    expect(second.status().privacy.mode).toBe("metadata-only");
  });

  test("source slice tool fails closed with a typed JSON error in metadata-only mode", async () => {
    const captured = capturePi();
    const runtime = registerChinaTargetedResumeExtension(captured.api);
    const tool = captured.tools.find((candidate) => candidate.name === "resume_read_source_slice")!;

    const rawResult = await tool.execute(
      "call-1",
      {
        runId: runtime.activeRunId,
        consumer: "evidence-reviewer",
        repositoryRoot: "/workspace/source",
        path: "/workspace/source/evidence.md",
        startLine: 1,
        endLine: 2,
        category: "evidence",
      },
      undefined,
      undefined,
      {},
    );
    const result = rawResult as {
      readonly content: readonly [{ readonly type: "text"; readonly text: string }];
      readonly isError?: boolean;
    };
    const envelope = JSON.parse(result.content[0].text) as Record<string, unknown>;

    expect(result.isError).toBe(true);
    expect(envelope).toMatchObject({
      ok: false,
      tool: "resume_read_source_slice",
      runId: runtime.activeRunId,
      error: { code: "metadata-only", retryable: false },
    });
    expect(result.content[0].text).not.toContain("source body sentinel");
  });

  test("compose rejects before spawning when no same-run approval receipt exists", async () => {
    const captured = capturePi();
    const runtime = registerChinaTargetedResumeExtension(captured.api);
    const tool = captured.tools.find((candidate) => candidate.name === "resume_compose_variants")!;

    const rawResult = await tool.execute(
      "call-compose-without-lock",
      { runId: runtime.activeRunId, payload: {} },
      undefined,
      undefined,
      {},
    );
    const result = rawResult as {
      readonly content: readonly [{ readonly type: "text"; readonly text: string }];
      readonly isError?: boolean;
    };
    const envelope = JSON.parse(result.content[0].text) as Record<string, unknown>;

    expect(result.isError).toBe(true);
    expect(envelope).toMatchObject({
      ok: false,
      tool: "resume_compose_variants",
      runId: runtime.activeRunId,
      error: { code: "APPROVAL_LOCK_REQUIRED", retryable: false },
    });
  });

  test("claim locking rejects evidence that lacks a same-run validation receipt", async () => {
    const captured = capturePi();
    const runtime = registerChinaTargetedResumeExtension(captured.api);
    const tool = captured.tools.find((candidate) => candidate.name === "resume_lock_approved_claims")!;

    const rawResult = await tool.execute(
      "call-lock-without-validation",
      {
        runId: runtime.activeRunId,
        sourceRoot: "/workspace/source",
        evidenceReceiptDigest: `sha256:${"0".repeat(64)}`,
        payload: {
          review_decisions: { schema_version: 1, decisions: [] },
          approved_safe_claims: {},
          output_mode: "targeted_application",
        },
      },
      undefined,
      undefined,
      {},
    );
    const result = rawResult as {
      readonly content: readonly [{ readonly type: "text"; readonly text: string }];
      readonly isError?: boolean;
    };
    const envelope = JSON.parse(result.content[0].text) as Record<string, unknown>;

    expect(result.isError).toBe(true);
    expect(envelope).toMatchObject({
      ok: false,
      tool: "resume_lock_approved_claims",
      runId: runtime.activeRunId,
      error: { code: "EVIDENCE_VALIDATION_REQUIRED", retryable: false },
    });
  });

  test("claim locking rejects forged caller confirmation booleans before receipt lookup", async () => {
    const captured = capturePi();
    const runtime = registerChinaTargetedResumeExtension(captured.api);
    const tool = captured.tools.find((candidate) => candidate.name === "resume_lock_approved_claims")!;
    const rawResult = await tool.execute(
      "call-lock-forged-confirmation",
      {
        runId: runtime.activeRunId,
        sourceRoot: "/workspace/source",
        evidenceReceiptDigest: `sha256:${"1".repeat(64)}`,
        payload: {
          review_decisions: { schema_version: 1, decisions: [] },
          approved_safe_claims: {},
          output_mode: "targeted_application",
          user_confirmations: { "evidence.fake": true },
        },
      },
      undefined,
      undefined,
      {},
    );
    const result = rawResult as {
      readonly content: readonly [{ readonly type: "text"; readonly text: string }];
      readonly isError?: boolean;
    };
    expect(result.isError).toBe(true);
    expect(JSON.parse(result.content[0].text)).toMatchObject({
      error: { code: "CALLER_CONFIRMATION_FORBIDDEN" },
    });
  });
});

describe("deterministic Plugin help", () => {
  test("resume-help renders overview and topics without invoking the model", async () => {
    const captured = capturePi();
    registerChinaTargetedResumeExtension(captured.api);
    const notifications: string[] = [];
    const help = captured.commands.get("resume-help")!;

    await help.handler("", commandContext(notifications));
    await help.handler("privacy", commandContext(notifications));

    expect(notifications[0]).toContain("China Targeted Resume Plugin");
    expect(notifications[0]).toContain("/resume-help [topic]");
    expect(notifications[0]).toContain("/resume-discover");
    expect(notifications[1]).toContain("metadata-only");
    expect(notifications[1]).toContain("reviewed-semantic");
    expect(captured.prompts).toEqual([]);
  });

  test("resume-help rejects unknown and multi-token topics", async () => {
    const captured = capturePi();
    registerChinaTargetedResumeExtension(captured.api);
    const notifications: string[] = [];
    const help = captured.commands.get("resume-help")!;

    await help.handler("unknown", commandContext(notifications));
    await help.handler("privacy extra", commandContext(notifications));

    expect(notifications).toHaveLength(2);
    expect(notifications.every((message) => message.includes("Unknown help topic"))).toBe(true);
    expect(notifications[0]).toContain("troubleshooting");
    expect(captured.prompts).toEqual([]);
  });

  test("resume-help offers bounded topic completions", () => {
    const captured = capturePi();
    registerChinaTargetedResumeExtension(captured.api);
    const complete = captured.commands.get("resume-help")!.getArgumentCompletions!;

    const allTopics = complete("");
    if (allTopics === null) throw new Error("resume-help topics are missing");
    expect(allTopics.map((item) => item.value)).toEqual([
      "init",
      "discover",
      "analyze",
      "generate",
      "audit",
      "status",
      "workflow",
      "privacy",
      "tools",
      "troubleshooting",
    ]);
    expect(complete("pr")).toEqual([
      {
        value: "privacy",
        label: "privacy",
        description: "Metadata-only and reviewed-semantic modes",
      },
    ]);
    expect(complete("privacy extra")).toBeNull();
  });

  test("every workflow command handles local help flags before domain parsing", async () => {
    const captured = capturePi();
    registerChinaTargetedResumeExtension(captured.api);
    const expectedByCommand: Readonly<Record<string, string>> = {
      "resume-init": "reviewed-semantic",
      "resume-discover": "SOURCE_ROOT",
      "resume-analyze": "independent",
      "resume-generate": "approval receipt",
      "resume-audit": "RESUME_VARIANTS_JSON",
      "resume-status": "run-id",
    };

    for (const [commandName, expected] of Object.entries(expectedByCommand)) {
      for (const flag of ["help", "-h", "--help"]) {
        const notifications: string[] = [];
        await captured.commands.get(commandName)!.handler(
          flag,
          commandContext(notifications),
        );
        expect(notifications.join("\n")).toContain(expected);
      }
    }
    expect(captured.prompts).toEqual([]);
  });
});

describe("slash command safety and status", () => {
  test("resume-generate warns and delegates orchestration without approving a claim", async () => {
    const captured = capturePi();
    registerChinaTargetedResumeExtension(captured.api);
    const notifications: string[] = [];

    await captured.commands.get("resume-generate")!.handler("", commandContext(notifications));

    expect(notifications.join("\n")).toContain("claim-lock result");
    expect(captured.prompts).toHaveLength(1);
    expect(captured.prompts[0]).toContain("Do not treat this command as approval");
    expect(captured.prompts[0]).toContain("resume_lock_approved_claims");
    expect(captured.prompts[0]).toContain("skills/china-targeted-resume/SKILL.md");
    expect(captured.prompts[0]).toContain("Do not substitute a same-name user-level Skill");
  });

  test("resume-status exposes private manifest status but no source bodies", async () => {
    const directory = await mkdtemp(join(tmpdir(), "ctr-extension-test-"));
    temporaryDirectories.push(directory);
    await chmod(directory, 0o700);
    const manifestPath = join(directory, "resume-variants.json");
    await writeFile(manifestPath, JSON.stringify({
      schema_version: 1,
      variants: [{
        variant: "recruiter_one_page",
        template: "ats-simple",
        target_pages: 1,
        actual_pages: 1,
        audit_success: true,
        pdf_success: true,
        artifacts: {
          document: "recruiter-one-page.resume-document.json",
          pdf: "recruiter-one-page.pdf",
        },
      }],
    }), { mode: 0o600 });
    await chmod(manifestPath, 0o600);
    const captured = capturePi();
    registerChinaTargetedResumeExtension(captured.api);
    const notifications: string[] = [];

    await captured.commands.get("resume-status")!.handler(manifestPath, commandContext(notifications));

    const status = JSON.parse(notifications.at(-1)!) as Record<string, unknown>;
    expect(status).toMatchObject({
      privacy: { mode: "metadata-only" },
      manifest: { schemaVersion: 1, variantCount: 1 },
    });
    expect(notifications.at(-1)).not.toContain("source body sentinel");
    expect(captured.prompts).toEqual([]);
  });

  test("reviewed status projects session audits without filesystem paths", async () => {
    const directory = await mkdtemp(join(tmpdir(), "PRIVATE-PATH-SENTINEL-"));
    temporaryDirectories.push(directory);
    await chmod(directory, 0o700);
    const sessionPath = join(directory, "PRIVATE-SESSION-SENTINEL.jsonl");
    await writeFile(sessionPath, "", { mode: 0o600 });
    await chmod(sessionPath, 0o600);
    const uid = typeof process.getuid === "function" ? process.getuid() : 0;
    const captured = capturePi();
    const runtime = registerChinaTargetedResumeExtension(captured.api);
    runtime.authorizeReviewedSemantic(runtime.activeRunId, {
      provider: "provider",
      model: "model",
      locality: "local",
      authorizationId: "auth-status",
      consumerIdentities: {
        main: { provider: "provider", model: "model", locality: "local" },
      },
      categories: ["evidence"],
      minimumSlices: [{
        path: "records/evidence.md",
        startLine: 1,
        endLine: 1,
        category: "evidence",
        consumer: "main",
        purpose: "status-test",
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
        path: directory,
        mode: 0o700,
        ownerUid: uid,
        expectedOwnerUid: uid,
        isDirectory: true,
      },
      retention: { strategy: "retain", cleanupSupported: false },
    });
    const notifications: string[] = [];

    await captured.commands.get("resume-status")!.handler("", commandContext(notifications));

    const rendered = notifications.at(-1)!;
    expect(rendered).not.toContain("PRIVATE-PATH-SENTINEL");
    expect(rendered).not.toContain("PRIVATE-SESSION-SENTINEL");
    expect(rendered).not.toContain(sessionPath);
    expect(JSON.parse(rendered)).toMatchObject({
      privacy: {
        mode: "reviewed-semantic",
        authorization: {
          present: true,
          sessionDirectoryPermissionsPrivate: true,
        },
      },
      sessionAudit: {
        status: "audited",
        retainedArtifact: true,
      },
    });
  });
});
