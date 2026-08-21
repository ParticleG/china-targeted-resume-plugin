import { lstat } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type {
  ExtensionAPI,
  ExtensionCommandContext,
} from "@oh-my-pi/pi-coding-agent";
import { readVariantManifest, summarizeVariantManifest } from "../manifest.ts";
import {
  ResumePluginRuntime,
  validateRunId,
  type ResumeRunStatus,
} from "../runtime.ts";
import { auditSessionJsonl } from "../privacy/index.ts";
import type {
  DisclosureConsumer,
  ProviderLocality,
  ReviewedSemanticAuthorizationInput,
  SessionAuditReport,
  SourceSliceDescriptor,
} from "../privacy/index.ts";
import {
  isResumeHelpRequest,
  resolveResumeHelpTopic,
  resumeHelpCompletions,
  resumeHelpError,
  resumeHelpText,
  type ResumeHelpTopic,
} from "./help.ts";

export const BUNDLED_RESUME_SKILL_PATH = fileURLToPath(
  new URL("../../../skills/china-targeted-resume/SKILL.md", import.meta.url),
);

export const RESUME_COMMAND_NAMES = [
  "resume-help",
  "resume-init",
  "resume-discover",
  "resume-analyze",
  "resume-generate",
  "resume-audit",
  "resume-status",
] as const;

export type ResumeCommandName = (typeof RESUME_COMMAND_NAMES)[number];

const MAX_PATH_ARGUMENT_LENGTH = 4096;
const ALLOWED_SLICE_METADATA_KEYS: Readonly<Record<string, true>> = Object.freeze({
  path: true,
  startLine: true,
  endLine: true,
  category: true,
  sourceId: true,
  sliceId: true,
  consumer: true,
  consumers: true,
  purpose: true,
});

function safePathArgument(raw: string, label: string): string {
  const value = raw.trim().replace(/^(["'])(.*)\1$/, "$2");
  if (
    !value ||
    value.length > MAX_PATH_ARGUMENT_LENGTH ||
    value.includes("\0") ||
    value.includes("\n") ||
    value.includes("\r")
  ) {
    throw new Error(`${label} must be one bounded filesystem path; do not paste source text into slash-command arguments`);
  }
  return value;
}

function modelIdentity(ctx: ExtensionCommandContext): {
  provider: string;
  model: string;
  locality?: ProviderLocality;
} | undefined {
  if (!ctx.model) return undefined;
  const candidate = ctx.model as unknown as Record<string, unknown>;
  const provider = candidate.provider;
  const model = candidate.id ?? candidate.model;
  if (typeof provider !== "string" || typeof model !== "string" || !provider.trim() || !model.trim()) return undefined;
  let locality: ProviderLocality | undefined;
  if (typeof candidate.baseUrl === "string") {
    try {
      const endpoint = new URL(candidate.baseUrl);
      if (/^https?:$/.test(endpoint.protocol)) {
        const host = endpoint.hostname.toLowerCase();
        locality = (
          host === "localhost" ||
          host === "::1" ||
          host.endsWith(".local") ||
          /^127\./.test(host) ||
          /^10\./.test(host) ||
          /^192\.168\./.test(host) ||
          /^172\.(?:1[6-9]|2\d|3[01])\./.test(host)
        ) ? "local" : "remote";
      }
    } catch {
      // Interactive authorization asks when endpoint locality is unobservable.
    }
  }
  return {
    provider: provider.trim(),
    model: model.trim(),
    ...(locality === undefined ? {} : { locality }),
  };
}

function parseMinimumSlices(raw: string): readonly SourceSliceDescriptor[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("Minimum slices must be a JSON array of path/startLine/endLine/category descriptors");
  }
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error("Reviewed-semantic mode requires at least one exact minimum slice");
  }
  return Object.freeze(parsed.map((value, index) => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new Error(`Minimum slice ${index + 1} must be an object`);
    }
    const record = value as Record<string, unknown>;
    if (Object.keys(record).some((key) => ALLOWED_SLICE_METADATA_KEYS[key] !== true)) {
      throw new Error(`Minimum slice ${index + 1} contains non-metadata fields`);
    }
    if (
      typeof record.path !== "string" ||
      typeof record.startLine !== "number" ||
      !Number.isSafeInteger(record.startLine) ||
      typeof record.endLine !== "number" ||
      !Number.isSafeInteger(record.endLine) ||
      record.startLine < 1 ||
      record.endLine < record.startLine ||
      typeof record.category !== "string" ||
      !record.category.trim() ||
      typeof record.purpose !== "string" ||
      !record.purpose.trim()
    ) {
      throw new Error(`Minimum slice ${index + 1} requires path, integer line bounds, category, and purpose`);
    }
    const singleConsumer = typeof record.consumer === "string" &&
      record.consumer.trim()
      ? record.consumer.trim()
      : undefined;
    const rawConsumers = Array.isArray(record.consumers) ? (record.consumers as unknown[]) : undefined;
    const manyConsumers = rawConsumers !== undefined && rawConsumers.every((entry: unknown) => typeof entry === "string" && entry.trim())
      ? rawConsumers.map((entry: unknown) => (entry as string).trim())
      : undefined;
    if (!singleConsumer && (!manyConsumers || manyConsumers.length === 0)) {
      throw new Error(`Minimum slice ${index + 1} requires at least one allowed consumer`);
    }
    return Object.freeze({
      path: record.path,
      startLine: record.startLine,
      endLine: record.endLine,
      category: record.category.trim(),
      purpose: record.purpose.trim(),
      ...(singleConsumer === undefined ? {} : { consumer: singleConsumer as DisclosureConsumer }),
      ...(manyConsumers === undefined ? {} : { consumers: Object.freeze(manyConsumers as DisclosureConsumer[]) }),
      ...(typeof record.sourceId === "string" && record.sourceId.trim() ? { sourceId: record.sourceId.trim() } : {}),
      ...(typeof record.sliceId === "string" && record.sliceId.trim() ? { sliceId: record.sliceId.trim() } : {}),
    });
  }));
}

async function configureReviewedSemantic(
  runtime: ResumePluginRuntime,
  runId: string,
  ctx: ExtensionCommandContext,
): Promise<boolean> {
  if (!ctx.hasUI) {
    ctx.ui.notify("Reviewed-semantic authorization requires the interactive OMP UI; the run remains metadata-only", "error");
    return false;
  }
  const identity = modelIdentity(ctx);
  const provider = identity?.provider ?? await ctx.ui.input("Reviewed-semantic provider", "Provider name");
  const model = identity?.model ?? await ctx.ui.input("Reviewed-semantic model", "Exact model ID");
  if (!provider?.trim() || !model?.trim()) {
    ctx.ui.notify("Provider and model are required; the run remains metadata-only", "warning");
    return false;
  }
  let locality = identity?.locality;
  if (locality === undefined) {
    const localityChoice = await ctx.ui.select("Where will main-model reviewed slices be processed?", [
      "Remote provider",
      "Local provider",
    ]);
    if (!localityChoice) return false;
    locality = localityChoice === "Local provider" ? "local" : "remote";
  }
  const taskProvider = await ctx.ui.input(
    "Built-in task provider",
    "Exact provider used by source/role/evidence/privacy reviewer tasks",
  );
  const taskModel = await ctx.ui.input(
    "Built-in task model",
    "Exact model ID used by source/role/evidence/privacy reviewer tasks",
  );
  if (!taskProvider?.trim() || !taskModel?.trim()) {
    ctx.ui.notify("Task provider and model are required; the run remains metadata-only", "warning");
    return false;
  }
  const taskLocalityChoice = await ctx.ui.select("Where will task reviewer slices be processed?", [
    "Remote provider",
    "Local provider",
  ]);
  if (!taskLocalityChoice) return false;
  const taskLocality: ProviderLocality = taskLocalityChoice === "Local provider" ? "local" : "remote";
  const categoriesRaw = await ctx.ui.input(
    "Authorized disclosure categories",
    "Comma-separated categories, for example: jd,evidence,policy",
  );
  const categories = categoriesRaw?.split(",").map((value) => value.trim()).filter(Boolean) ?? [];
  if (categories.length === 0) {
    ctx.ui.notify("At least one disclosure category is required; the run remains metadata-only", "warning");
    return false;
  }
  const slicesRaw = await ctx.ui.input(
    "Exact minimum slices",
    '[{"path":"/source/file.md","startLine":10,"endLine":18,"category":"evidence","consumer":"evidence-reviewer","purpose":"verify one claim"}]',
  );
  if (!slicesRaw) return false;
  let minimumSlices: readonly SourceSliceDescriptor[];
  try {
    minimumSlices = parseMinimumSlices(slicesRaw);
  } catch (error) {
    ctx.ui.notify(error instanceof Error ? error.message : "Minimum slice metadata is invalid", "error");
    return false;
  }
  const sessionJsonlPath = ctx.sessionManager.getSessionFile();
  if (!sessionJsonlPath) {
    ctx.ui.notify("OMP session JSONL is disabled or unavailable; reviewed-semantic mode cannot be authorized", "error");
    return false;
  }
  const sessionMetadata = await lstat(sessionJsonlPath).catch(() => undefined);
  const expectedOwnerUid = typeof process.getuid === "function" ? process.getuid() : undefined;
  const mainSessionPrivate = sessionMetadata !== undefined &&
    sessionMetadata.isFile() &&
    !sessionMetadata.isSymbolicLink() &&
    (sessionMetadata.mode & 0o077) === 0 &&
    (expectedOwnerUid === undefined || sessionMetadata.uid === expectedOwnerUid);
  if (!mainSessionPrivate) {
    ctx.ui.notify(
      "OMP main session JSONL must be a current-user-owned private regular file with no group/other permissions; reviewed-semantic mode remains disabled",
      "error",
    );
    return false;
  }
  if (!sessionMetadata) return false;
  const sessionDirectoryPath = dirname(sessionJsonlPath);
  const sessionDirectoryMetadata = await lstat(sessionDirectoryPath).catch(() => undefined);
  const sessionDirectoryPrivate = sessionDirectoryMetadata !== undefined &&
    sessionDirectoryMetadata.isDirectory() &&
    !sessionDirectoryMetadata.isSymbolicLink() &&
    (sessionDirectoryMetadata.mode & 0o077) === 0 &&
    (sessionDirectoryMetadata.mode & 0o700) === 0o700 &&
    (expectedOwnerUid === undefined || sessionDirectoryMetadata.uid === expectedOwnerUid);
  if (!sessionDirectoryPrivate) {
    ctx.ui.notify(
      "OMP session directory must be a current-user-owned private directory with no group/other permissions; reviewed-semantic mode remains disabled",
      "error",
    );
    return false;
  }
  if (!sessionDirectoryMetadata) return false;
  const observedMode = sessionMetadata.mode & 0o777;
  const observedDirectoryMode = sessionDirectoryMetadata.mode & 0o777;
  const disclosure = [
    `Main provider/model: ${provider.trim()} / ${model.trim()} (${locality})`,
    `Task provider/model: ${taskProvider.trim()} / ${taskModel.trim()} (${taskLocality})`,
    `Categories: ${categories.join(", ")}`,
    `Minimum slices: ${minimumSlices.map((slice) => `${slice.path}:${slice.startLine}-${slice.endLine} [${slice.purpose}; ${slice.consumer ?? slice.consumers?.join("|")}]`).join(", ")}`,
    `OMP JSONL: ${sessionJsonlPath} (mode ${observedMode.toString(8).padStart(3, "0")})`,
    `OMP session directory: ${sessionDirectoryPath} (mode ${observedDirectoryMode.toString(8).padStart(3, "0")})`,
    "Built-in task/advisor JSONLs are retained under this directory; each actual file mode and disclosure scope must be audited after fan-out.",
    "Retention: OMP-owned JSONL is retained; no supported Extension deletion guarantee is available.",
    "Always forbidden: contacts, credentials, whole repositories, and every F6/P3 body.",
  ].join("\n");
  const confirmed = await ctx.ui.confirm(
    "Authorize reviewed-semantic disclosure for this run?",
    disclosure,
  );
  if (!confirmed) {
    ctx.ui.notify("Authorization declined; the run remains metadata-only", "info");
    return false;
  }
  const authorization: ReviewedSemanticAuthorizationInput = {
    provider: provider.trim(),
    model: model.trim(),
    locality,
    consumerIdentities: {
      main: { provider: provider.trim(), model: model.trim(), locality },
      "source-mapper": {
        provider: taskProvider.trim(),
        model: taskModel.trim(),
        locality: taskLocality,
      },
      "role-analyst": {
        provider: taskProvider.trim(),
        model: taskModel.trim(),
        locality: taskLocality,
      },
      "requirement-reviewer": {
        provider: taskProvider.trim(),
        model: taskModel.trim(),
        locality: taskLocality,
      },
      "evidence-reviewer": {
        provider: taskProvider.trim(),
        model: taskModel.trim(),
        locality: taskLocality,
      },
      "contribution-reviewer": {
        provider: taskProvider.trim(),
        model: taskModel.trim(),
        locality: taskLocality,
      },
      "privacy-reviewer": {
        provider: taskProvider.trim(),
        model: taskModel.trim(),
        locality: taskLocality,
      },
    },
    categories,
    minimumSlices,
    sessionJsonlPath,
    session: {
      path: sessionJsonlPath,
      mode: observedMode,
      ownerUid: sessionMetadata.uid,
      ...(expectedOwnerUid === undefined ? {} : { expectedOwnerUid }),
      isRegularFile: true,
    },
    sessionDirectory: {
      path: sessionDirectoryPath,
      mode: observedDirectoryMode,
      ownerUid: sessionDirectoryMetadata.uid,
      ...(expectedOwnerUid === undefined ? {} : { expectedOwnerUid }),
      isDirectory: true,
    },
    retention: {
      strategy: "retain",
      cleanupSupported: false,
      cleanupLimits: ["OMP 17.3.7 exposes no verified Extension API for selective session JSONL deletion"],
      deletionGuaranteed: false,
    },
  };
  try {
    runtime.authorizeReviewedSemantic(runId, authorization);
  } catch (error) {
    ctx.ui.notify(error instanceof Error ? error.message : "Reviewed-semantic authorization failed closed", "error");
    return false;
  }
  ctx.ui.notify(`Run ${runId} is authorized for only the recorded reviewed-semantic slices`, "warning");
  return true;
}

function workflowPrompt(
  stage: Exclude<
    ResumeCommandName,
    "resume-help" | "resume-init" | "resume-status"
  >,
  runId: string,
  argument?: string,
): string {
  const context = argument === undefined ? "" : `\nAuthorized metadata argument: ${JSON.stringify(argument)}`;
  const instructions: Record<typeof stage, string> = {
    "resume-discover": "Use the bundled china-targeted-resume Skill. Discover metadata with resume_discover_structure. Use OMP's built-in task tool for source-mapper work; never imitate task orchestration and never request raw slices in metadata-only mode.",
    "resume-analyze": "Use the bundled china-targeted-resume Skill. Run independent role, requirement, evidence, contribution, and privacy review with OMP's built-in task tool, aggregate strict structured decisions, escalate hard disagreements, then call deterministic IR validators.",
    "resume-generate": "Use the bundled china-targeted-resume Skill. Do not treat this command as approval. Lock claims only through resume_lock_approved_claims after deterministic validation and required user confirmations, then compose and render every manifest variant.",
    "resume-audit": "Use the bundled china-targeted-resume Skill. Read resume-variants.json metadata and call resume_inspect_variants so every manifest-listed PDF is inspected. Report failures and retained reviewed-semantic OMP JSONL honestly.",
  };
  return [
    `[china-targeted-resume run ${runId}]`,
    `Read and follow the canonical bundled Skill at ${JSON.stringify(BUNDLED_RESUME_SKILL_PATH)}.`,
    "Do not substitute a same-name user-level Skill for this Plugin workflow.",
    instructions[stage],

  ].join("\n") + context;
}
function sessionAuditSummary(report: SessionAuditReport): Readonly<Record<string, unknown>> {
  return Object.freeze({
    status: "audited",
    ok: report.ok,
    exists: report.exists,
    regularFile: report.regularFile,
    privatePermissions: report.privatePermissions,
    ...(report.observedMode === undefined ? {} : { observedMode: report.observedMode }),
    ownerMatches: report.ownerMatches,
    parentDirectory: Object.freeze({
      exists: report.parentDirectory.exists,
      isDirectory: report.parentDirectory.isDirectory,
      privatePermissions: report.parentDirectory.privatePermissions,
      ...(report.parentDirectory.observedMode === undefined
        ? {}
        : { observedMode: report.parentDirectory.observedMode }),
      ownerMatches: report.parentDirectory.ownerMatches,
    }),
    tree: Object.freeze({
      directoryCount: report.tree.directoryCount,
      fileCount: report.tree.fileCount,
      jsonlCount: report.tree.jsonlCount,
      markdownCount: report.tree.markdownCount,
      weakDirectoryCount: report.tree.weakDirectoryCount,
      weakFileCount: report.tree.weakFileCount,
      receiptUnprovenFileCount: report.tree.receiptUnprovenFileCount,
      disclosedSliceCount: report.tree.disclosedSliceCount,
      outOfScopeSliceCount: report.tree.outOfScopeSliceCount,
      forbiddenSentinelCount: report.tree.forbiddenSentinelCount,
      malformedLineCount: report.tree.malformedLineCount,
      scopeProof: report.tree.scopeProof,
    }),
    effectivePrivacy: report.effectivePrivacy,
    disclosedSliceCount: report.disclosedSliceCount,
    outOfScopeSliceCount: report.outOfScopeSliceCount,
    forbiddenSentinelCount: report.forbiddenSentinelCount,
    malformedLineCount: report.malformedLineCount,
    lineLimitExceeded: report.lineLimitExceeded,
    retainedArtifact: report.retainedArtifact,
    cleanup: report.cleanup,
    deletionClaimed: report.deletionClaimed,
    errors: Object.freeze([...report.errors]),
  });
}

function resumeStatusSummary(status: ResumeRunStatus): Readonly<Record<string, unknown>> {
  const authorization = status.privacy.authorization;
  return Object.freeze({
    runId: status.runId,
    privacy: Object.freeze({
      mode: status.privacy.mode,
      rawSourceAllowed: status.privacy.rawSourceAllowed,
      authorizationId: status.privacy.authorizationId,
      authorization: Object.freeze({
        present: authorization.present,
        authorizationId: authorization.authorizationId,
        provider: authorization.provider,
        model: authorization.model,
        locality: authorization.locality,
        consumerIdentities: authorization.consumerIdentities,
        categories: authorization.categories,
        categoryCount: authorization.categoryCount,
        minimumSliceCount: authorization.minimumSliceCount,
        sessionJsonlMode: authorization.sessionJsonlMode,
        sessionJsonlPermissionsPrivate: authorization.sessionJsonlPermissionsPrivate,
        sessionJsonlOwnerMatches: authorization.sessionJsonlOwnerMatches,
        sessionDirectoryMode: authorization.sessionDirectoryMode,
        sessionDirectoryPermissionsPrivate: authorization.sessionDirectoryPermissionsPrivate,
        sessionDirectoryOwnerMatches: authorization.sessionDirectoryOwnerMatches,
        authorizedAt: authorization.authorizedAt,
      }),
      retention: status.privacy.retention,
    }),
    completedTools: status.completedTools,
    lastTool: status.lastTool,
    manifest: status.manifest,
    approval: status.approval,
    evidenceValidation: status.evidenceValidation,
    sourcePolicy: status.sourcePolicy,
    confirmationCount: status.confirmationCount,
  });
}

function showInlineHelp(
  rawArgs: string,
  topic: ResumeHelpTopic,
  ctx: ExtensionCommandContext,
): boolean {
  if (!isResumeHelpRequest(rawArgs)) return false;
  ctx.ui.notify(resumeHelpText(topic), "info");
  return true;
}

export function registerResumeCommands(pi: ExtensionAPI, runtime: ResumePluginRuntime): void {
  pi.registerCommand("resume-help", {
    description: "Show deterministic Plugin usage; /resume-help [topic]",
    getArgumentCompletions: resumeHelpCompletions,
    handler: async (rawArgs, ctx) => {
      const topic = resolveResumeHelpTopic(rawArgs);
      if (topic === undefined) {
        ctx.ui.notify(resumeHelpError(rawArgs), "error");
        return;
      }
      ctx.ui.notify(resumeHelpText(topic), "info");
    },
  });

  pi.registerCommand("resume-init", {
    description: "Initialize a private run; use /resume-help init",
    handler: async (rawArgs, ctx) => {
      if (showInlineHelp(rawArgs, "init", ctx)) return;
      const tokens = rawArgs.trim() ? rawArgs.trim().split(/\s+/) : [];
      const reviewedSemantic = tokens.includes("--reviewed-semantic");
      const positional = tokens.filter((token) => token !== "--reviewed-semantic");
      if (positional.length > 1) {
        ctx.ui.notify("Usage: /resume-init [run-id] [--reviewed-semantic]", "error");
        return;
      }
      let runId: string;
      try {
        runId = runtime.initialize(positional[0]);
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : "Run initialization failed", "error");
        return;
      }
      if (!reviewedSemantic) {
        ctx.ui.notify(`Run ${runId} initialized in metadata-only mode`, "info");
        return;
      }
      const authorized = await configureReviewedSemantic(runtime, runId, ctx);
      if (authorized) {
        pi.appendEntry("china-targeted-resume/privacy-authorization", runtime.status(runId).privacy);
      }
    },
  });

  pi.registerCommand("resume-discover", {
    description: "Discover source metadata; use /resume-help discover",
    handler: async (rawArgs, ctx) => {
      if (showInlineHelp(rawArgs, "discover", ctx)) return;
      try {
        const sourceRoot = safePathArgument(rawArgs, "Source root");
        pi.sendUserMessage(workflowPrompt("resume-discover", runtime.activeRunId, sourceRoot));
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : "Invalid source root", "error");
      }
    },
  });

  pi.registerCommand("resume-analyze", {
    description: "Start independent analysis; use /resume-help analyze",
    handler: async (rawArgs, ctx) => {
      if (showInlineHelp(rawArgs, "analyze", ctx)) return;
      try {
        if (rawArgs.trim()) runtime.activate(validateRunId(rawArgs));
        pi.sendUserMessage(workflowPrompt("resume-analyze", runtime.activeRunId));
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : "Invalid run ID", "error");
      }
    },
  });

  pi.registerCommand("resume-generate", {
    description: "Generate from locked claims; use /resume-help generate",
    handler: async (rawArgs, ctx) => {
      if (showInlineHelp(rawArgs, "generate", ctx)) return;
      try {
        if (rawArgs.trim()) runtime.activate(validateRunId(rawArgs));
        const status = runtime.status();
        if (status.approval === undefined) {
          ctx.ui.notify("No deterministic claim-lock result is recorded; generation must not continue until the gate passes", "warning");
        }
        pi.sendUserMessage(workflowPrompt("resume-generate", runtime.activeRunId));
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : "Invalid run ID", "error");
      }
    },
  });

  pi.registerCommand("resume-audit", {
    description: "Audit a variant manifest; use /resume-help audit",
    handler: async (rawArgs, ctx) => {
      if (showInlineHelp(rawArgs, "audit", ctx)) return;
      try {
        const manifestPath = safePathArgument(rawArgs, "resume-variants.json path");
        const manifest = await readVariantManifest(manifestPath);
        runtime.recordManifest(summarizeVariantManifest(manifest));
        const privacy = runtime.status().privacy;
        const sessionAudit = privacy.authorization.present
          ? sessionAuditSummary(auditSessionJsonl(runtime.privacyState()))
          : {
              status: "not_applicable",
              retainedArtifact: false,
              deletionClaimed: false,
              errors: [],
            };
        ctx.ui.notify(JSON.stringify({ manifest: runtime.status().manifest, sessionAudit }, null, 2), "info");
        pi.sendUserMessage(workflowPrompt("resume-audit", runtime.activeRunId, manifestPath));
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : "Variant manifest could not be read", "error");
      }
    },
  });

  pi.registerCommand("resume-status", {
    description: "Show path-free run status; use /resume-help status",
    handler: async (rawArgs, ctx) => {
      if (showInlineHelp(rawArgs, "status", ctx)) return;
      try {
        const argument = rawArgs.trim();
        if (argument) {
          if (argument.endsWith(".json")) {
            const manifest = await readVariantManifest(safePathArgument(argument, "resume-variants.json path"));
            runtime.recordManifest(summarizeVariantManifest(manifest));
          } else {
            runtime.activate(validateRunId(argument));
          }
        }
        const status = runtime.status();
        const sessionAudit = status.privacy.authorization.present
          ? sessionAuditSummary(auditSessionJsonl(runtime.privacyState()))
          : {
              status: "not_applicable",
              retainedArtifact: false,
              deletionClaimed: false,
              errors: [],
            };
        ctx.ui.notify(
          JSON.stringify({ ...resumeStatusSummary(status), sessionAudit }, null, 2),
          "info",
        );
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : "Resume status is unavailable", "error");
      }
    },
  });
}
