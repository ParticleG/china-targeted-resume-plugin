import { existsSync, lstatSync, readFileSync, readdirSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import type {
  DisclosureConsumer,
  ProviderLocality,
  RetentionPolicy,
  RunPrivacyState,
  SessionArtifactFileAuditSummary,
  SessionArtifactTreeAuditSummary,
  SessionAuditOptions,
  SessionAuditReport,
  SessionCleanupOptions,
  SessionCleanupResult,
  SessionDirectoryAuditSummary,
  SessionJsonlObservation,
  SourceSliceDescriptor,
} from "./types";
import {
  canonicalConsumer,
  containsContact,
  containsCredential,
  containsF6P3,
  hasForbiddenSentinel,
  isSliceWithin,
  normalizeSessionObservation,
  normalizeSliceDescriptor,
  hasPrivateDirectoryPermissions,
  hasPrivatePermissions,
  ownerMatches,
  parseMode,
} from "./guards";

const RAW_KEYS = /^(?:content|body|text|raw|quote|markdown|source|sourceSlice|source_slice|slice|prompt|message|result|output|toolResult|tool_result|value)$/i;
const PATH_KEYS = /^(?:path|sourcePath|source_path|file|filename)$/i;
const ID_KEYS = /^(?:sliceId|slice_id|sourceId|source_id)$/i;
const AUTH_ID_KEYS = /^(?:authorizationId|authorization_id|authId|auth_id)$/i;
const PROVIDER_KEYS = /^(?:provider|providerId|provider_id)$/i;
const MODEL_KEYS = /^(?:model|modelId|model_id)$/i;
const START_KEYS = /^(?:startLine|start_line|lineStart|line_start)$/i;
const END_KEYS = /^(?:endLine|end_line|lineEnd|line_end)$/i;
const CATEGORY_KEYS = /^(?:category|categories)$/i;
const CONSUMER_KEYS = /^(?:consumer|consumers)$/i;
const PURPOSE_KEYS = /^(?:purpose|disclosurePurpose|disclosure_purpose)$/i;
const LOCALITY_KEYS = /^(?:locality|providerLocality|local_vs_remote|localVsRemote)$/i;
const DEFAULT_MAX_LINES = 10000;

interface DisclosedSlice {
  readonly descriptor?: SourceSliceDescriptor;
  readonly authorizationId?: string;
  readonly provider?: string;
  readonly model?: string;
  readonly locality?: ProviderLocality;
  readonly content: string;
}
interface WalkContext {
  readonly path?: string;
  readonly sourceId?: string;
  readonly sliceId?: string;
  readonly authorizationId?: string;
  readonly provider?: string;
  readonly model?: string;
  readonly locality?: ProviderLocality;
  readonly consumer?: DisclosureConsumer;
  readonly consumers?: readonly DisclosureConsumer[];
  readonly purpose?: string;
  readonly startLine?: number;
  readonly endLine?: number;
  readonly category?: string;
  readonly rawParent: boolean;
}

function defaultCleanup(policy: RetentionPolicy): SessionCleanupResult {
  return Object.freeze({
    supported: policy.cleanupSupported,
    attempted: false,
    deleted: false,
    verified: false,
    ...(policy.cleanupLimits[0] === undefined ? {} : { limit: policy.cleanupLimits[0] }),
    note: policy.cleanupSupported
      ? "Cleanup was not attempted by the privacy audit"
      : "Cleanup support is unavailable; any OMP artifact is reported as retained",
  });
}
function pathFromObject(value: Record<string, unknown>): string | undefined {
  for (const [key, candidate] of Object.entries(value)) {
    if (PATH_KEYS.test(key) && typeof candidate === "string") return candidate;
  }
  return undefined;
}

function numberFromObject(value: Record<string, unknown>, pattern: RegExp): number | undefined {
  for (const [key, candidate] of Object.entries(value)) {
    if (pattern.test(key) && typeof candidate === "number" && Number.isSafeInteger(candidate)) return candidate;
  }
  return undefined;
}
function stringFromObject(
  value: Record<string, unknown>,
  pattern: RegExp,
  preferredKey: string,
): string | undefined {
  const wanted = preferredKey.toLowerCase();
  for (const [key, candidate] of Object.entries(value)) {
    const normalizedKey = key.toLowerCase().replaceAll("_", "");
    if (typeof candidate === "string" && pattern.test(key) && normalizedKey === wanted) return candidate;
  }
  return undefined;
}
function consumersFromObject(value: Record<string, unknown>): readonly DisclosureConsumer[] | undefined {
  for (const [key, candidate] of Object.entries(value)) {
    if (!CONSUMER_KEYS.test(key)) continue;
    const raw = typeof candidate === "string" ? [candidate] : Array.isArray(candidate) ? candidate : [];
    const normalized: DisclosureConsumer[] = [];
    for (const entry of raw) {
      if (typeof entry !== "string") return undefined;
      try {
        normalized.push(canonicalConsumer(entry as DisclosureConsumer));
      } catch {
        return undefined;
      }
    }
    return normalized.length === 0 ? undefined : Object.freeze(normalized);
  }
  return undefined;
}
function localityFromObject(value: Record<string, unknown>): ProviderLocality | undefined {
  for (const [key, candidate] of Object.entries(value)) {
    if (LOCALITY_KEYS.test(key) && (candidate === "local" || candidate === "remote")) return candidate;
  }
  return undefined;
}

function collectDisclosures(value: unknown, context: WalkContext, result: DisclosedSlice[]): void {
  if (typeof value === "string") {
    if (context.rawParent && value.length > 0) {
      result.push({
        ...(context.path === undefined
          ? {}
          : {
              descriptor: {
                path: context.path,
                ...(context.sourceId === undefined ? {} : { sourceId: context.sourceId }),
                ...(context.sliceId === undefined ? {} : { sliceId: context.sliceId }),
                ...(context.consumer === undefined ? {} : { consumer: context.consumer }),
                ...(context.consumers === undefined ? {} : { consumers: context.consumers }),
                ...(context.purpose === undefined ? {} : { purpose: context.purpose }),
                ...(context.startLine === undefined ? {} : { startLine: context.startLine }),
                ...(context.endLine === undefined ? {} : { endLine: context.endLine }),
                ...(context.category === undefined ? {} : { category: context.category }),
              },
            }),
        ...(context.authorizationId === undefined ? {} : { authorizationId: context.authorizationId }),
        ...(context.provider === undefined ? {} : { provider: context.provider }),
        ...(context.model === undefined ? {} : { model: context.model }),
        ...(context.locality === undefined ? {} : { locality: context.locality }),
        content: value,
      });
    }
    return;
  }
  if (Array.isArray(value)) {
    for (const child of value) collectDisclosures(child, context, result);
    return;
  }
  if (!value || typeof value !== "object") return;
  const object = value as Record<string, unknown>;
  const path = pathFromObject(object) ?? context.path;
  const sourceId = stringFromObject(object, ID_KEYS, "sourceId") ?? context.sourceId;
  const sliceId = stringFromObject(object, ID_KEYS, "sliceId") ?? context.sliceId;
  const authorizationId = stringFromObject(object, AUTH_ID_KEYS, "authorizationId") ?? context.authorizationId;
  const provider = stringFromObject(object, PROVIDER_KEYS, "provider") ?? context.provider;
  const model = stringFromObject(object, MODEL_KEYS, "model") ?? context.model;
  const consumers = consumersFromObject(object) ?? context.consumers;
  const consumer = consumers?.[0] ?? context.consumer;
  const purpose = stringFromObject(object, PURPOSE_KEYS, "purpose") ?? context.purpose;
  const locality = localityFromObject(object) ?? context.locality;
  const startLine = numberFromObject(object, START_KEYS) ?? context.startLine;
  const endLine = numberFromObject(object, END_KEYS) ?? context.endLine;
  const category = categoryFromObject(object) ?? context.category;
  for (const [key, child] of Object.entries(object)) {
    const metadataKey =
      PATH_KEYS.test(key) ||
      ID_KEYS.test(key) ||
      AUTH_ID_KEYS.test(key) ||
      PROVIDER_KEYS.test(key) ||
      MODEL_KEYS.test(key) ||
      CONSUMER_KEYS.test(key) ||
      PURPOSE_KEYS.test(key) ||
      LOCALITY_KEYS.test(key) ||
      START_KEYS.test(key) ||
      END_KEYS.test(key) ||
      CATEGORY_KEYS.test(key);
    const rawParent = !metadataKey && (context.rawParent || RAW_KEYS.test(key));
    collectDisclosures(
      child,
      {
        ...(path === undefined ? {} : { path }),
        ...(sourceId === undefined ? {} : { sourceId }),
        ...(sliceId === undefined ? {} : { sliceId }),
        ...(authorizationId === undefined ? {} : { authorizationId }),
        ...(provider === undefined ? {} : { provider }),
        ...(model === undefined ? {} : { model }),
        ...(locality === undefined ? {} : { locality }),
        ...(consumer === undefined ? {} : { consumer }),
        ...(consumers === undefined ? {} : { consumers }),
        ...(purpose === undefined ? {} : { purpose }),
        ...(startLine === undefined ? {} : { startLine }),
        ...(endLine === undefined ? {} : { endLine }),
        ...(category === undefined ? {} : { category }),
        rawParent,
      },
      result,
    );
  }
}

function objectRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function collectSessionDisclosures(
  parsed: unknown,
  result: DisclosedSlice[],
): void {
  const root = objectRecord(parsed);
  if (!root) return;

  for (const key of ("sourceSlice" in root
    ? ["sourceSlice"]
    : "source_slice" in root
      ? ["source_slice"]
      : [])) {
    collectDisclosures(root[key], { rawParent: false }, result);
  }

  const message = objectRecord(root.message);
  if (message?.role !== "toolResult") return;
  const directTool = message.toolName;
  const content = Array.isArray(message.content) ? message.content : [];
  for (const item of content) {
    const entry = objectRecord(item);
    if (entry?.type !== "text" || typeof entry.text !== "string") continue;
    let envelope: unknown;
    try {
      envelope = JSON.parse(entry.text);
    } catch {
      continue;
    }
    const toolResult = objectRecord(envelope);
    if (!toolResult || toolResult.ok !== true) continue;
    const tool = toolResult.tool ?? directTool;
    if (tool !== "resume_read_source_slice") continue;
    collectDisclosures(toolResult.data, { rawParent: false }, result);
  }
}

function categoryFromObject(value: Record<string, unknown>): string | undefined {
  for (const [key, candidate] of Object.entries(value)) {
    if (CATEGORY_KEYS.test(key) && typeof candidate === "string") return candidate;
  }
  return undefined;
}


function descriptorsFor(state: RunPrivacyState): readonly SourceSliceDescriptor[] {
  return state.authorization?.minimumSlices ?? [];
}
function scopePath(path: string, root: string | undefined): string {
  const normalizedPath = path.replaceAll("\\", "/");
  if (!root) return normalizedPath;
  const normalizedRoot = root.replaceAll("\\", "/").replace(/\/$/, "");
  const prefix = `${normalizedRoot}/`;
  if (normalizedPath === normalizedRoot) return "";
  if (normalizedPath.startsWith(prefix)) return normalizedPath.slice(prefix.length);
  return normalizedPath;
}

function lineHasForbiddenSentinel(line: string): boolean {
  return hasForbiddenSentinel(line) || containsContact(line) || containsCredential(line) || containsF6P3(line);
}


function auditFileObservation(
  path: string,
  state: RunPrivacyState,
  supplied: SessionJsonlObservation | undefined,
): { exists: boolean; regularFile: boolean; privatePermissions: boolean; mode?: number; ownerMatches: boolean } {
  if (!existsSync(path)) {
    return { exists: false, regularFile: false, privatePermissions: false, ownerMatches: false };
  }
  let stat: { mode: number; uid?: number; isFile: () => boolean };
  try {
    const candidate = lstatSync(path);
    stat = candidate;
  } catch {
    return { exists: false, regularFile: false, privatePermissions: false, ownerMatches: false };
  }
  const mode = stat.mode & 0o7777;
  const regularFile = stat.isFile();
  const privatePermissions = (mode & 0o077) === 0;
  const expectedUid = supplied?.expectedOwnerUid ?? state.authorization?.sessionObservation.expectedOwnerUid;
  const expectedOwner = supplied?.expectedOwner ?? state.authorization?.sessionObservation.expectedOwner;
  const matched = ownerMatches(stat.uid, undefined, expectedUid, expectedOwner);
  return { exists: true, regularFile, privatePermissions, mode, ownerMatches: matched };
}
function auditArtifactTree(
  state: RunPrivacyState,
  sessionPath: string,
  options: SessionAuditOptions,
): {
  readonly parent: SessionDirectoryAuditSummary;
  readonly tree: SessionArtifactTreeAuditSummary;
  readonly effectivePrivacy: "private" | "weak-directory" | "weak-file" | "unavailable";
  readonly errors: readonly string[];
} {
  const parentPath = dirname(sessionPath);
  const errors: string[] = [];
  let parent: SessionDirectoryAuditSummary;
  try {
    const stat = lstatSync(parentPath);
    const mode = stat.mode & 0o7777;
    const privatePermissions = hasPrivateDirectoryPermissions(mode);
    const ownerMatchesValue = ownerMatches(
      stat.uid,
      undefined,
      state.authorization?.sessionDirectoryObservation.expectedOwnerUid,
      state.authorization?.sessionDirectoryObservation.expectedOwner,
    );
    parent = Object.freeze({
      path: parentPath,
      exists: true,
      isDirectory: stat.isDirectory(),
      privatePermissions,
      observedMode: mode,
      ownerMatches: ownerMatchesValue,
    });
    if (!stat.isDirectory() || !privatePermissions || !ownerMatchesValue) {
      errors.push("OMP session parent directory is not private and owned by the run user");
    }
  } catch {
    parent = Object.freeze({ path: parentPath, exists: false, isDirectory: false, privatePermissions: false, ownerMatches: false });
    errors.push("OMP session parent directory could not be observed");
  }
  const files: SessionArtifactFileAuditSummary[] = [];
  const allowed = descriptorsFor(state).map((slice) => ({
    ...slice,
    path: scopePath(slice.path, options.repositoryRoot),
  }));
  const queue = [parentPath];
  const maxEntries = options.maxTreeEntries ?? 512;
  let scanned = 0;
  let directoryCount = 0;
  let fileCount = 0;
  let jsonlCount = 0;
  let markdownCount = 0;
  let weakDirectoryCount = 0;
  let weakFileCount = 0;
  let receiptUnprovenFileCount = 0;
  let disclosedSliceCount = 0;
  let outOfScopeSliceCount = 0;
  let forbiddenSentinelCount = 0;
  let malformedLineCount = 0;
  while (queue.length > 0 && scanned < maxEntries) {
    const current = queue.shift();
    if (!current) continue;
    let names: string[];
    try {
      names = readdirSync(current);
    } catch {
      errors.push("OMP session artifact directory could not be enumerated");
      continue;
    }
    for (const name of names) {
      if (scanned >= maxEntries) break;
      scanned += 1;
      const child = join(current, name);
      let stat: {
        readonly mode: number;
        readonly uid: number;
        readonly isDirectory: () => boolean;
        readonly isFile: () => boolean;
        readonly isSymbolicLink: () => boolean;
      };
      try {
        stat = lstatSync(child);
      } catch {
        errors.push("OMP session artifact entry could not be observed");
        continue;
      }
      if (stat.isSymbolicLink()) {
        errors.push("OMP session artifact tree contains a symlink");
        continue;
      }
      const mode = stat.mode & 0o7777;
      const privatePermissions = stat.isDirectory()
        ? hasPrivateDirectoryPermissions(mode)
        : hasPrivatePermissions(mode);
      const ownerMatchesValue = ownerMatches(
        stat.uid,
        undefined,
        state.authorization?.sessionDirectoryObservation.expectedOwnerUid,
        state.authorization?.sessionDirectoryObservation.expectedOwner,
      );
      if (!ownerMatchesValue) {
        errors.push("OMP session artifact owner does not match the run owner");
      }
      if (stat.isDirectory()) {
        directoryCount += 1;
        if (!privatePermissions) {
          weakDirectoryCount += 1;
          errors.push("OMP session artifact tree contains a weak directory");
        }
        queue.push(child);
        continue;
      }
      if (!stat.isFile()) continue;
      fileCount += 1;
      const lower = name.toLowerCase();
      const kind: SessionArtifactFileAuditSummary["kind"] =
        lower.endsWith(".jsonl") ? "jsonl" : lower.endsWith(".md") ? "markdown" : "other";
      if (kind === "jsonl") jsonlCount += 1;
      if (kind === "markdown") markdownCount += 1;
      if (!privatePermissions) weakFileCount += 1;
      let containsAuthorizedReceipt = false;
      if (kind === "jsonl" || kind === "markdown") {
        try {
          const rawBody = readFileSync(child, "utf8");
          const body = rawBody.slice(0, 262_144);
          if (rawBody.length > body.length) {
            errors.push("OMP session artifact file audit byte limit exceeded");
            receiptUnprovenFileCount += 1;
          }
          if (kind === "markdown" && lineHasForbiddenSentinel(body)) {
            forbiddenSentinelCount += 1;
          }
          const auth = state.authorization;
          containsAuthorizedReceipt =
            auth !== undefined &&
            body.includes(auth.authorizationId) &&
            body.includes(auth.provider) &&
            body.includes(auth.model);
          if (child !== sessionPath && kind === "jsonl") {
            const bodyLines = body.split(/\r?\n/);
            if (bodyLines.length > 1000) {
              errors.push("OMP session artifact file audit line limit exceeded");
              receiptUnprovenFileCount += 1;
            }
            for (const line of bodyLines.slice(0, 1000)) {
              if (!line.trim()) continue;
              if (lineHasForbiddenSentinel(line)) forbiddenSentinelCount += 1;
              let parsed: unknown;
              try {
                parsed = JSON.parse(line);
              } catch {
                malformedLineCount += 1;
                continue;
              }
              const disclosures: DisclosedSlice[] = [];
              collectSessionDisclosures(parsed, disclosures);
              for (const disclosure of disclosures) {
                disclosedSliceCount += 1;
                if (lineHasForbiddenSentinel(disclosure.content)) forbiddenSentinelCount += 1;
                if (!disclosure.descriptor) {
                  outOfScopeSliceCount += 1;
                  continue;
                }
                try {
                  const descriptor = normalizeSliceDescriptor({
                    ...disclosure.descriptor,
                    path: scopePath(disclosure.descriptor.path, options.repositoryRoot),
                  });
                  const receiptConsumers = [
                    ...(descriptor.consumer === undefined ? [] : [canonicalConsumer(descriptor.consumer)]),
                    ...(descriptor.consumers ?? []).map((entry: DisclosureConsumer) => canonicalConsumer(entry)),
                  ];
                  const identityMatches = receiptConsumers.some((receiptConsumer) => {
                    const identityMap = auth?.consumerIdentities;
                    const identity = identityMap === undefined ? undefined : identityMap[receiptConsumer];
                    return identity !== undefined && disclosure.authorizationId === auth?.authorizationId &&
                      disclosure.provider === identity.provider && disclosure.model === identity.model &&
                      disclosure.locality === identity.locality;
                  });
                  if (!identityMatches || !allowed.some((candidate) => isSliceWithin(descriptor, candidate))) {
                    outOfScopeSliceCount += 1;
                  }
                } catch {
                  outOfScopeSliceCount += 1;
                }
              }
            }
          }
        } catch {
          errors.push("OMP session artifact file could not be inspected");
        }
        if (!containsAuthorizedReceipt) receiptUnprovenFileCount += 1;
      }
      files.push(Object.freeze({ path: child, kind, mode, privatePermissions, ownerMatches: ownerMatchesValue, containsAuthorizedReceipt }));
    }
  }
  if (scanned >= maxEntries) errors.push("OMP session artifact tree audit entry limit exceeded");
  if (weakFileCount > 0) errors.push("OMP session artifact files include group/world-accessible modes; directory privacy is reported separately");
  const scopeProof: SessionArtifactTreeAuditSummary["scopeProof"] =
    receiptUnprovenFileCount > 0 || errors.length > 0
      ? "receipts-incomplete"
      : jsonlCount + markdownCount > 0
        ? "receipts-verified"
        : "not-applicable";
  const effectivePrivacy = !parent.exists
    ? "unavailable"
    : weakDirectoryCount > 0 || !parent.privatePermissions || !parent.ownerMatches
      ? "weak-directory"
      : weakFileCount > 0
        ? "weak-file"
        : "private";
  return {
    parent,
    tree: Object.freeze({
      directoryCount,
      fileCount,
      jsonlCount,
      markdownCount,
      weakDirectoryCount,
      weakFileCount,
      receiptUnprovenFileCount,
      disclosedSliceCount,
      outOfScopeSliceCount,
      forbiddenSentinelCount,
      malformedLineCount,
      files: Object.freeze(files),
      scopeProof,
    }),
    effectivePrivacy,
    errors: Object.freeze(errors),
  };
}

/**
 * Audit the OMP-owned session JSONL without returning its raw lines.  The audit
 * intentionally treats unsupported cleanup as retained data instead of making
 * a deletion claim.
 */
export function auditSessionJsonl(
  state: RunPrivacyState,
  options: SessionAuditOptions = {},
): SessionAuditReport {
  const path = options.path ?? state.authorization?.sessionJsonlPath ?? "";
  const cleanup = options.cleanup ?? defaultCleanup(state.retention);
  const errors: string[] = [];
  if (!path) {
    const emptyParent: SessionDirectoryAuditSummary = Object.freeze({
      path: "",
      exists: false,
      isDirectory: false,
      privatePermissions: false,
      ownerMatches: false,
    });
    const emptyTree: SessionArtifactTreeAuditSummary = Object.freeze({
      directoryCount: 0,
      fileCount: 0,
      jsonlCount: 0,
      markdownCount: 0,
      weakDirectoryCount: 0,
      weakFileCount: 0,
      receiptUnprovenFileCount: 0,
      disclosedSliceCount: 0,
      outOfScopeSliceCount: 0,
      forbiddenSentinelCount: 0,
      malformedLineCount: 0,
      files: Object.freeze([]),
      scopeProof: "not-applicable",
    });
    return Object.freeze({
      ok: false,
      path: "",
      exists: false,
      regularFile: false,
      privatePermissions: false,
      ownerMatches: false,
      parentDirectory: emptyParent,
      tree: emptyTree,
      effectivePrivacy: "unavailable",
      disclosedSliceCount: 0,
      outOfScopeSliceCount: 0,
      forbiddenSentinelCount: 0,
      malformedLineCount: 0,
      lineLimitExceeded: false,
      retainedArtifact: false,
      cleanup,
      deletionClaimed: false,
      errors: Object.freeze(["No OMP session JSONL path is available"]),
    });
  }
  const suppliedObservation = options.observation ? normalizeSessionObservation(options.observation, path) : undefined;
  const file = auditFileObservation(path, state, suppliedObservation);
  const deletionClaimed =
    cleanup.supported && cleanup.attempted && cleanup.deleted && cleanup.verified && !file.exists;
  if (!file.exists && !deletionClaimed) errors.push("OMP session JSONL artifact does not exist");
  if (file.exists && cleanup.deleted && cleanup.verified) {
    errors.push("Cleanup was reported verified but the OMP session artifact remains");
  }
  if (file.exists && !file.regularFile) errors.push("OMP session JSONL artifact is not a regular file");
  if (file.exists && !file.privatePermissions) errors.push("OMP session JSONL permissions are not 0600-equivalent");
  if (file.exists && !file.ownerMatches) errors.push("OMP session JSONL owner does not match the run owner");
  const treeAudit = auditArtifactTree(state, path, options);
  errors.push(...treeAudit.errors);
  if (treeAudit.tree.scopeProof === "receipts-incomplete") {
    errors.push("Subagent/task artifact scope proof is incomplete because serialized receipts are absent");
  }

  let disclosedSliceCount = treeAudit.tree.disclosedSliceCount;
  let outOfScopeSliceCount = treeAudit.tree.outOfScopeSliceCount;
  let forbiddenSentinelCount = treeAudit.tree.forbiddenSentinelCount;
  let malformedLineCount = treeAudit.tree.malformedLineCount;
  let lineLimitExceeded = false;
  const maxLines = options.maxLines ?? DEFAULT_MAX_LINES;
  if (file.exists && file.regularFile) {
    let content: string;
    try {
      content = readFileSync(path, "utf8");
    } catch {
      content = "";
      errors.push("OMP session JSONL artifact could not be read");
    }
    const lines = content.split(/\r?\n/);
    if (lines.length > maxLines) {
      lineLimitExceeded = true;
      errors.push("OMP session JSONL audit line limit exceeded");
    }
    const allowed = descriptorsFor(state).map((slice) => ({
      ...slice,
      path: scopePath(slice.path, options.repositoryRoot),
    }));
    for (const line of lines.slice(0, maxLines)) {
      if (!line.trim()) continue;
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        malformedLineCount += 1;
        if (lineHasForbiddenSentinel(line)) forbiddenSentinelCount += 1;
        continue;
      }
      const disclosures: DisclosedSlice[] = [];
      collectSessionDisclosures(parsed, disclosures);
      for (const disclosure of disclosures) {
        if (lineHasForbiddenSentinel(disclosure.content)) {
          forbiddenSentinelCount += 1;
        }
        disclosedSliceCount += 1;
        if (!disclosure.descriptor) {
          outOfScopeSliceCount += 1;
          continue;
        }
        let descriptor: SourceSliceDescriptor;
        try {
          descriptor = normalizeSliceDescriptor(disclosure.descriptor);
        } catch {
          outOfScopeSliceCount += 1;
          continue;
        }
        descriptor = { ...descriptor, path: scopePath(descriptor.path, options.repositoryRoot) };
        const authorization = state.authorization;
        const receiptConsumers = [
          ...(descriptor.consumer === undefined ? [] : [canonicalConsumer(descriptor.consumer)]),
          ...(descriptor.consumers ?? []).map((entry: DisclosureConsumer) => canonicalConsumer(entry)),
        ];
        const identityMatches = receiptConsumers.some((receiptConsumer) => {
          const identityMap = authorization?.consumerIdentities;
          const identity = identityMap === undefined ? undefined : identityMap[receiptConsumer];
          return (
            identity !== undefined &&
            disclosure.provider === identity.provider &&
            disclosure.model === identity.model &&
            disclosure.locality === identity.locality
          );
        });
        if (
          authorization === undefined ||
          disclosure.authorizationId !== authorization.authorizationId ||
          !identityMatches
        ) {
          outOfScopeSliceCount += 1;
          continue;
        }
        if (!allowed.some((candidate) => isSliceWithin(descriptor, candidate))) outOfScopeSliceCount += 1;
      }
    }
  }
  if (forbiddenSentinelCount > 0) errors.push("Forbidden contact, credential, or F6/P3 sentinel found in OMP session JSONL");
  if (malformedLineCount > 0) errors.push("OMP session JSONL contains malformed lines");
  if (disclosedSliceCount > 0 && outOfScopeSliceCount > 0) errors.push("OMP session JSONL contains a slice outside authorized minimum scope");

  const retainedArtifact = (file.exists || treeAudit.tree.fileCount > 0) && !deletionClaimed;
  const ok =
    treeAudit.effectivePrivacy === "private" &&
    (deletionClaimed ||
      (file.exists &&
        file.regularFile &&
        file.privatePermissions &&
        file.ownerMatches &&
        treeAudit.tree.scopeProof !== "receipts-incomplete" &&
        forbiddenSentinelCount === 0 &&
        outOfScopeSliceCount === 0 &&
        malformedLineCount === 0 &&
        !lineLimitExceeded));
  return Object.freeze({
    ok,
    path,
    exists: file.exists,
    regularFile: file.regularFile,
    privatePermissions: file.privatePermissions,
    ...(file.mode === undefined ? {} : { observedMode: parseMode(file.mode) }),
    ownerMatches: file.ownerMatches,
    parentDirectory: treeAudit.parent,
    tree: treeAudit.tree,
    effectivePrivacy: treeAudit.effectivePrivacy,
    disclosedSliceCount,
    outOfScopeSliceCount,
    forbiddenSentinelCount,
    malformedLineCount,
    lineLimitExceeded,
    retainedArtifact,
    cleanup,
    deletionClaimed,
    errors: Object.freeze(errors),
  });
}

export function reportSessionCleanup(
  state: RunPrivacyState,
  result: SessionCleanupResult,
): SessionCleanupResult {
  const supported = state.retention.cleanupSupported && result.supported;
  const deleted = supported && result.attempted && result.deleted;
  const verified = deleted && result.verified;
  return Object.freeze({
    supported,
    attempted: result.attempted,
    deleted,
    verified,
    ...(result.limit === undefined ? {} : { limit: result.limit }),
    note: verified
      ? "Cleanup was supported and independently verified"
      : supported
        ? result.note ?? "Cleanup was not independently verified; artifact must be reported as retained"
        : "Cleanup is unsupported or outside the recorded policy; artifact must be reported as retained",
  });
}
export function cleanupSessionJsonl(
  state: RunPrivacyState,
  options: SessionCleanupOptions = {},
): SessionCleanupResult {
  const path = state.authorization?.sessionJsonlPath;
  const policy = state.retention;
  const limit = policy.cleanupLimits[0];
  if (!policy.cleanupSupported || policy.strategy !== "cleanup-on-stop" || !path) {
    return Object.freeze({
      supported: false,
      attempted: false,
      deleted: false,
      verified: false,
      ...(limit === undefined ? {} : { limit }),
      note: "Cleanup is unsupported by the recorded OMP policy; retained artifact must be reported",
    });
  }
  const remove = options.remove ?? ((target: string) => unlinkSync(target));
  if (!existsSync(path)) {
    return Object.freeze({
      supported: true,
      attempted: false,
      deleted: false,
      verified: true,
      ...(limit === undefined ? {} : { limit }),
      note: "No session artifact existed when cleanup was requested",
    });
  }
  try {
    remove(path);
  } catch {
    return Object.freeze({
      supported: true,
      attempted: true,
      deleted: false,
      verified: false,
      ...(limit === undefined ? {} : { limit }),
      note: "Cleanup failed; retained artifact must be reported",
    });
  }
  const verified = !existsSync(path);
  return Object.freeze({
    supported: true,
    attempted: true,
    deleted: verified,
    verified,
    ...(limit === undefined ? {} : { limit }),
    note: verified
      ? "Cleanup was supported and independently verified"
      : "Cleanup was not independently verified; retained artifact must be reported",
  });
}

export const auditOmpSessionJsonl = auditSessionJsonl;
