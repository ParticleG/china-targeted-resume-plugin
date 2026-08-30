import { lstatSync } from "node:fs";
import { dirname } from "node:path";
import type {
  CanonicalDisclosureConsumer,
  DisclosureConsumer,
  RetentionPolicy,
  RetentionPolicyInput,
  SessionDirectoryObservation,
  SessionDirectoryObservationInput,
  SessionJsonlObservation,
  SessionJsonlObservationInput,
  SourceSliceDescriptor,
  MinimumSliceInput,
} from "./types";

export class PrivacyError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, string | number | boolean>> | undefined;

  constructor(
    code: string,
    message: string,
    details?: Readonly<Record<string, string | number | boolean>>,
  ) {
    super(message);
    this.name = "PrivacyError";
    this.code = code;
    this.details = details;
  }
}

export class PrivacyAuthorizationError extends PrivacyError {
  constructor(
    code:
      | "invalid-provider"
      | "invalid-categories"
      | "invalid-slices"
      | "invalid-session"
      | "unsafe-authorization"
      | "invalid-retention"
      | "mode-already-authorized"
      | "run-mismatch",
    message: string,
  ) {
    super(code, message);
    this.name = "PrivacyAuthorizationError";
  }
}

export class SourceSlicePolicyError extends PrivacyError {
  constructor(code: string, message: string) {
    super(code, message);
    this.name = "SourceSlicePolicyError";
  }
}

const FORBIDDEN_METADATA_KEY = /^(?:body|content|raw|quote|text|markdown|prompt|secret|secrets?|credential(?:s)?|contacts?|contact[-_ ]?(?:info|details)?|phones?|telephone|emails?|addresses?|tokens?|api[-_]?keys?|private[-_]?keys?)$/i;
const FORBIDDEN_WORD = /(?:contact|e[-_ ]?mail|phone|telephone|address|linkedin|credential|password|passwd|secret|token|api[-_ ]?key|private(?:[-_ ]?(?:key|data|info|notes?))?|sensitive|access[-_ ]?key|bearer|authorization|cookie|id[_-]?rsa|\.env|\.pem)/i;
const SECRET_VALUE = /(?:^|\b)(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})(?:\b|$)/;
const EMAIL_VALUE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i;
const PHONE_VALUE = /(?:\+?\d[\d .()_-]{7,}\d)/;
const SECRET_ASSIGNMENT = /(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|authorization)\s*[:=]/i;
const F6_P3_VALUE = /(?:^|[^a-z0-9])(?:f6|p3)(?:$|[^a-z0-9])/i;

export const FORBIDDEN_SENTINEL_RE = new RegExp(
  `${FORBIDDEN_WORD.source}|${SECRET_VALUE.source}|${SECRET_ASSIGNMENT.source}|${EMAIL_VALUE.source}|${PHONE_VALUE.source}|${F6_P3_VALUE.source}`,
  "i",
);

export function canonicalConsumer(consumer: DisclosureConsumer): CanonicalDisclosureConsumer {
  switch (consumer) {
    case "main":
    case "main-model":
      return "main";
    case "source-mapper":
      return "source-mapper";
    case "role-analyst":
      return "role-analyst";
    case "requirement-reviewer":
      return "requirement-reviewer";
    case "evidence-reviewer":
      return "evidence-reviewer";
    case "contribution-reviewer":
      return "contribution-reviewer";
    case "privacy-reviewer":
      return "privacy-reviewer";
    case "resume-advisor":
    case "advisor":
      return "resume-advisor";
    default:
      throw new SourceSlicePolicyError("consumer-forbidden", "Unknown disclosure consumer");
  }
}

export function parseMode(value: number | string): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value & 0o7777;
  }
  if (typeof value !== "string") {
    throw new PrivacyAuthorizationError("invalid-session", "Session file mode is required");
  }
  const trimmed = value.trim();
  const symbolic = /^(?:-)?r[-w][-x]r[-w][-x]r[-w][-x]$/.exec(trimmed);
  if (symbolic) {
    const bits = trimmed.replace(/^-/, "");
    const toBits = (chunk: string): number =>
      (chunk[0] === "r" ? 4 : 0) + (chunk[1] === "w" ? 2 : 0) + (chunk[2] === "x" ? 1 : 0);
    return (toBits(bits.slice(0, 3)) << 6) | (toBits(bits.slice(3, 6)) << 3) | toBits(bits.slice(6, 9));
  }
  const octal = /^(?:0o)?([0-7]{3,4})$/.exec(trimmed);
  if (!octal) {
    throw new PrivacyAuthorizationError("invalid-session", "Session file mode must be octal or symbolic");
  }
  return Number.parseInt(octal[1] ?? "", 8) & 0o7777;
}

export function hasPrivatePermissions(mode: number | string): boolean {
  return (parseMode(mode) & 0o077) === 0;
}
export function hasPrivateDirectoryPermissions(mode: number | string): boolean {
  const parsed = parseMode(mode);
  return (parsed & 0o077) === 0 && (parsed & 0o700) === 0o700;
}

function currentUid(): number | undefined {
  const maybeProcess = globalThis as typeof globalThis & {
    process?: { getuid?: () => number };
  };
  return maybeProcess.process?.getuid?.();
}

function currentUser(): string | undefined {
  const maybeProcess = globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> };
  };
  return maybeProcess.process?.env?.USER ?? maybeProcess.process?.env?.USERNAME;
}
export function ownerMatches(
  ownerUid: number | undefined,
  owner: string | undefined,
  expectedOwnerUid?: number,
  expectedOwner?: string,
): boolean {
  if (ownerUid !== undefined) {
    const expected = expectedOwnerUid ?? currentUid();
    return expected !== undefined && ownerUid === expected;
  }
  if (owner !== undefined) {
    const expected = expectedOwner ?? currentUser();
    return expected !== undefined && owner === expected;
  }
  return false;
}

export function normalizeSessionObservation(
  input: SessionJsonlObservationInput,
  fallbackPath?: string,
): SessionJsonlObservation {
  const path = input.path ?? fallbackPath;
  if (!path || typeof path !== "string" || path.trim().length === 0) {
    throw new PrivacyAuthorizationError("invalid-session", "OMP session JSONL path is required");
  }
  const rawMode = input.mode ?? input.observedMode;
  if (rawMode === undefined) {
    throw new PrivacyAuthorizationError("invalid-session", "Observed session file mode is required");
  }
  const mode = parseMode(rawMode);
  const ownerUid = input.ownerUid ?? input.observedOwnerUid;
  const owner = input.owner ?? input.observedOwner;
  const isRegularFile = input.isRegularFile ?? input.regularFile ?? true;
  const privatePermissions = hasPrivatePermissions(mode);
  const matched = ownerMatches(ownerUid, owner, input.expectedOwnerUid, input.expectedOwner);
  return Object.freeze({
    path: path.trim(),
    mode,
    ...(ownerUid === undefined ? {} : { ownerUid }),
    ...(owner === undefined ? {} : { owner }),
    ...(input.expectedOwnerUid === undefined ? {} : { expectedOwnerUid: input.expectedOwnerUid }),
    ...(input.expectedOwner === undefined ? {} : { expectedOwner: input.expectedOwner }),
    isRegularFile,
    privatePermissions,
    ownerMatches: matched,
  });
}
export function normalizeSessionDirectoryObservation(
  input: SessionDirectoryObservationInput,
  fallbackPath?: string,
): SessionDirectoryObservation {
  const path = input.path ?? fallbackPath;
  if (!path || typeof path !== "string" || path.trim().length === 0) {
    throw new PrivacyAuthorizationError("invalid-session", "OMP session directory path is required");
  }
  const rawMode = input.mode ?? input.observedMode;
  if (rawMode === undefined) {
    throw new PrivacyAuthorizationError("invalid-session", "Observed session directory mode is required");
  }
  const mode = parseMode(rawMode);
  const ownerUid = input.ownerUid ?? input.observedOwnerUid;
  const owner = input.owner ?? input.observedOwner;
  const isDirectory = input.isDirectory ?? input.directory ?? true;
  const privatePermissions = hasPrivateDirectoryPermissions(mode);
  const matched = ownerMatches(ownerUid, owner, input.expectedOwnerUid, input.expectedOwner);
  return Object.freeze({
    path: path.trim(),
    mode,
    ...(ownerUid === undefined ? {} : { ownerUid }),
    ...(owner === undefined ? {} : { owner }),
    ...(input.expectedOwnerUid === undefined ? {} : { expectedOwnerUid: input.expectedOwnerUid }),
    ...(input.expectedOwner === undefined ? {} : { expectedOwner: input.expectedOwner }),
    isDirectory,
    privatePermissions,
    ownerMatches: matched,
  });
}

export function observeSessionDirectory(sessionJsonlPath: string): SessionDirectoryObservation {
  const path = dirname(sessionJsonlPath);
  let mode: number;
  let ownerUid: number;
  let isDirectory: boolean;
  try {
    const observed = lstatSync(path);
    mode = observed.mode & 0o7777;
    ownerUid = observed.uid;
    isDirectory = observed.isDirectory();
  } catch {
    throw new PrivacyAuthorizationError("invalid-session", "OMP session directory could not be observed");
  }
  if (!isDirectory) {
    throw new PrivacyAuthorizationError("invalid-session", "OMP session parent must be a directory");
  }
  const expectedOwnerUid = currentUid();
  return normalizeSessionDirectoryObservation(
    {
      path,
      mode,
      ownerUid,
      ...(expectedOwnerUid === undefined ? {} : { expectedOwnerUid }),
      isDirectory: true,
    },
    path,
  );
}

export function normalizeRetention(input: RetentionPolicyInput | undefined): RetentionPolicy {
  const source = input ?? {};
  const strategy = source.strategy ?? "not-applicable";
  const allowed: readonly string[] = [
    "not-applicable",
    "cleanup-on-stop",
    "retain-until-expiry",
    "retain",
  ];
  if (!allowed.includes(strategy)) {
    throw new PrivacyAuthorizationError("invalid-retention", "Unknown session retention strategy");
  }
  if (
    source.maxAgeSeconds !== undefined &&
    (!Number.isSafeInteger(source.maxAgeSeconds) || source.maxAgeSeconds <= 0)
  ) {
    throw new PrivacyAuthorizationError("invalid-retention", "Retention max age must be a positive integer");
  }
  const cleanupLimits = [
    ...(source.cleanupLimit ? [source.cleanupLimit] : []),
    ...(source.cleanupLimits ?? []),
  ]
    .map((entry) => normalizeMetadataString(entry, "retention cleanup limit"))
    .filter((entry, index, all) => all.indexOf(entry) === index);
  const cleanupSupported = source.cleanupSupported ?? false;
  // A caller may request cleanup but cannot make an unsupported deletion claim.
  const deletionGuarantee = source.deletionGuaranteed === true && cleanupSupported ? "verified" : "not-guaranteed";
  return Object.freeze({
    strategy,
    ...(source.maxAgeSeconds === undefined ? {} : { maxAgeSeconds: source.maxAgeSeconds }),
    cleanupSupported,
    cleanupLimits: Object.freeze(cleanupLimits),
    deletionGuarantee,
  });
}

export function normalizeMetadataString(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new PrivacyAuthorizationError("unsafe-authorization", `${label} must be a string`);
  }
  const normalized = value.trim();
  if (!normalized || normalized.length > 512 || /[\u0000-\u001f\u007f]/.test(normalized)) {
    throw new PrivacyAuthorizationError("unsafe-authorization", `${label} is not safe metadata`);
  }
  return normalized;
}

export function assertSafeMetadata(value: unknown, key = "metadata", depth = 0): void {
  if (depth > 5) {
    throw new PrivacyAuthorizationError("unsafe-authorization", "Authorization metadata is too deeply nested");
  }
  if (typeof value === "string") {
    if (value.length > 512 || /[\u0000\u0001-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) {
      throw new PrivacyAuthorizationError("unsafe-authorization", `${key} contains non-metadata content`);
    }
    // Session storage paths are metadata even when a private directory name
    // contains words such as "privacy". Source-slice paths are still checked.
    const sessionPathMetadata = /(?:sessionJsonlPath|observedSession\.path|sessionDirectory\.path)$/i.test(key);
    const opaqueIdentifierMetadata = /(?:^|\.)(?:runId|authorizationId|requestId|inputId|evidenceId|claimId|digest)$/i.test(key);
    if (
      !sessionPathMetadata &&
      (FORBIDDEN_WORD.test(value) || (!opaqueIdentifierMetadata && F6_P3_VALUE.test(value)) || SECRET_VALUE.test(value) || SECRET_ASSIGNMENT.test(value))
    ) {
      throw new PrivacyAuthorizationError("unsafe-authorization", `${key} contains forbidden metadata`);
    }
    return;
  }
  if (typeof value === "number" || typeof value === "boolean" || value === undefined || value === null) return;
  if (Array.isArray(value)) {
    value.forEach((entry, index) => assertSafeMetadata(entry, `${key}[${index}]`, depth + 1));
    return;
  }
  if (typeof value === "object") {
    for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>)) {
      if (FORBIDDEN_METADATA_KEY.test(childKey)) {
        throw new PrivacyAuthorizationError("unsafe-authorization", `${key} contains source material`);
      }
      assertSafeMetadata(childValue, `${key}.${childKey}`, depth + 1);
    }
  }
}

export function hasForbiddenSentinel(value: string): boolean {
  return FORBIDDEN_SENTINEL_RE.test(value);
}

export function containsContact(value: string): boolean {
  return EMAIL_VALUE.test(value) || PHONE_VALUE.test(value) || /(?:contact|e[-_ ]?mail|phone|telephone|address|linkedin)/i.test(value);
}

export function containsCredential(value: string): boolean {
  return SECRET_VALUE.test(value) || SECRET_ASSIGNMENT.test(value) || /(?:credential|password|passwd|secret|token|api[-_ ]?key|private[-_ ]?key|access[-_ ]?key|bearer|authorization|cookie|\.env|id[_-]?rsa)/i.test(value);
}

export function containsF6P3(value: string): boolean {
  return F6_P3_VALUE.test(value);
}

function normalizeSlicePath(path: string): string {
  const normalized = normalizeMetadataString(path, "slice path").replaceAll("\\", "/");
  if (
    normalized === "." ||
    normalized === ".." ||
    normalized === "/" ||
    normalized === "**" ||
    normalized === "*" ||
    /\s{2,}/.test(normalized) ||
    (/\s/.test(normalized) && !normalized.includes("/")) ||
    normalized.endsWith("/") ||
    normalized.includes("//") ||
    normalized.split("/").some((part) => part === "..") ||
    /[*?{}[\]]/.test(normalized)
  ) {
    throw new PrivacyAuthorizationError("invalid-slices", "Slice path must name a bounded file");
  }
  return normalized.replace(/^\.\//, "");
}

export function normalizeSliceDescriptor(input: MinimumSliceInput): SourceSliceDescriptor {
  if (typeof input === "string") {
    const raw = normalizeSlicePath(input);
    const match = /^(.*?)(?:#|:)?L(\d+)(?:[-_]L?(\d+))?$/i.exec(raw);
    if (!match) return Object.freeze({ path: raw });
    const startLine = Number.parseInt(match[2] ?? "", 10);
    const endLine = match[3] ? Number.parseInt(match[3], 10) : startLine;
    return normalizeSliceDescriptor({ path: match[1] ?? raw, startLine, endLine });
  }
  if (!input || typeof input !== "object") {
    throw new PrivacyAuthorizationError("invalid-slices", "Minimum slices must be path descriptors");
  }
  const path = normalizeSlicePath(input.path);
  const startLine = input.startLine ?? input.lineStart;
  const endLine = input.endLine ?? input.lineEnd;
  if (
    (startLine !== undefined && (!Number.isSafeInteger(startLine) || startLine < 1)) ||
    (endLine !== undefined && (!Number.isSafeInteger(endLine) || endLine < 1)) ||
    (startLine !== undefined && endLine !== undefined && endLine < startLine)
  ) {
    throw new PrivacyAuthorizationError("invalid-slices", "Slice line range is invalid");
  }
  if (input.category !== undefined) normalizeMetadataString(input.category, "slice category");
  if (input.sourceId !== undefined) normalizeMetadataString(input.sourceId, "slice source ID");
  if (input.sliceId !== undefined) normalizeMetadataString(input.sliceId, "slice ID");
  if (input.purpose !== undefined) normalizeMetadataString(input.purpose, "slice purpose");
  const consumer = input.consumer === undefined ? undefined : canonicalConsumer(input.consumer);
  const consumers = input.consumers?.map((entry) => canonicalConsumer(entry));
  if (consumers !== undefined && consumers.length === 0) {
    throw new PrivacyAuthorizationError("invalid-slices", "Slice consumers must not be empty");
  }
  const allConsumers = [...(consumer === undefined ? [] : [consumer]), ...(consumers ?? [])];
  const uniqueConsumers = allConsumers.filter((entry, index, all) => all.indexOf(entry) === index);
  assertSafeMetadata(
    { category: input.category, sourceId: input.sourceId, sliceId: input.sliceId, purpose: input.purpose, consumer, consumers: uniqueConsumers },
    "slice metadata",
  );
  return Object.freeze({
    path,
    ...(startLine === undefined ? {} : { startLine }),
    ...(endLine === undefined ? {} : { endLine }),
    ...(input.category === undefined ? {} : { category: input.category.trim() }),
    ...(input.sourceId === undefined ? {} : { sourceId: input.sourceId.trim() }),
    ...(input.sliceId === undefined ? {} : { sliceId: input.sliceId.trim() }),
    ...(consumer === undefined ? {} : { consumer }),
    ...(uniqueConsumers.length === 0 ? {} : { consumers: Object.freeze(uniqueConsumers) }),
    ...(input.purpose === undefined ? {} : { purpose: input.purpose.trim() }),
  });
}

export function isSliceWithin(request: SourceSliceDescriptor, allowed: SourceSliceDescriptor): boolean {
  if (request.path !== allowed.path) return false;
  if (allowed.category !== undefined && request.category !== allowed.category) return false;
  if (allowed.sourceId !== undefined && request.sourceId !== allowed.sourceId) return false;
  if (allowed.sliceId !== undefined && request.sliceId !== allowed.sliceId) return false;
  const requestConsumers = [
    ...(request.consumer === undefined ? [] : [canonicalConsumer(request.consumer)]),
    ...(request.consumers ?? []).map((entry) => canonicalConsumer(entry)),
  ];
  const allowedConsumers = [
    ...(allowed.consumer === undefined ? [] : [canonicalConsumer(allowed.consumer)]),
    ...(allowed.consumers ?? []).map((entry) => canonicalConsumer(entry)),
  ];
  if (allowedConsumers.length === 0 || requestConsumers.length === 0) return false;
  if (!requestConsumers.some((entry) => allowedConsumers.includes(entry))) return false;
  if (allowed.purpose !== undefined && request.purpose !== allowed.purpose) return false;
  if (request.purpose === undefined) return false;
  if (allowed.startLine === undefined && allowed.endLine === undefined) {
    return (
      (request.startLine === undefined && request.endLine === undefined) ||
      (request.startLine !== undefined && request.endLine !== undefined)
    );
  }
  if (request.startLine === undefined || request.endLine === undefined) return false;
  const start = allowed.startLine ?? 1;
  const end = allowed.endLine ?? Number.MAX_SAFE_INTEGER;
  return request.startLine >= start && request.endLine <= end;
}

export function isLikelyWholeRepository(request: { path: string; wholeRepository?: boolean; repositoryRoot?: string }): boolean {
  if (request.wholeRepository === true) return true;
  const path = request.path.trim().replaceAll("\\", "/").replace(/\/$/, "");
  const root = request.repositoryRoot?.trim().replaceAll("\\", "/").replace(/\/$/, "");
  return (
    path === "" ||
    path === "." ||
    path === "/" ||
    path === ".." ||
    path === "**" ||
    path === "*" ||
    (root !== undefined && root.length > 0 && path === root)
  );
}

export function normalizeTimestamp(value: string | number | Date | undefined, fallback: Date = new Date()): string {
  const date = value instanceof Date ? new Date(value.getTime()) : value === undefined ? fallback : new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new PrivacyAuthorizationError("unsafe-authorization", "Authorization timestamp is invalid");
  }
  return date.toISOString();
}

export function safeRunId(value: string | undefined, fallback: string): string {
  const runId = value === undefined ? fallback : normalizeMetadataString(value, "run ID");
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(runId)) {
    throw new PrivacyAuthorizationError("run-mismatch", "Run ID must be a bounded identifier");
  }
  return runId;
}
export function safeAuthorizationId(value: string | undefined, fallback: string): string {
  const id = value === undefined ? fallback : normalizeMetadataString(value, "authorization ID");
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(id)) {
    throw new PrivacyAuthorizationError("unsafe-authorization", "Authorization ID must be a bounded identifier");
  }
  return id;
}
