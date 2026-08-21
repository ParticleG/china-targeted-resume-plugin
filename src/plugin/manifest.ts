import { basename, dirname, isAbsolute, resolve } from "node:path";
import {
  inspectSecureDirectory,
  readContainedFileSnapshot,
  SecureIoError,
  type ContainedFileSnapshot,
  type SecureDirectoryInspection,
} from "../kernel/secure-io.ts";
import type { ManifestStatusSummary, VariantStatusSummary } from "./runtime.ts";

const MAX_MANIFEST_BYTES = 1024 * 1024;
const SAFE_ARTIFACT_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/;

export type VariantArtifactKind = "document" | "pdf";

export interface VariantManifestEntry {
  readonly variant: string;
  readonly targetPages: number;
  readonly actualPages?: number;
  readonly auditSuccess: boolean;
  readonly pdfSuccess: boolean;
  readonly artifacts: Readonly<Record<string, string>>;
}

export interface VariantManifest {
  readonly schemaVersion: 1;
  readonly variants: readonly VariantManifestEntry[];
}

export interface ResolvedVariantArtifact {
  readonly variant: string;
  readonly path: string;
}

export class ManifestContractError extends Error {
  override readonly name = "ManifestContractError";
  readonly code: string;

  constructor(code: string, message: string, options: ErrorOptions = {}) {
    super(message, options);
    this.code = code;
  }
}

interface SecureManifestContext {
  readonly runDirectory: string;
  readonly manifest: ContainedFileSnapshot;
}

const STRICT_UTF8_DECODER = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
function ownerUid(): number {
  const getuid = process.getuid;
  if (typeof getuid !== "function") {
    throw new ManifestContractError("OWNER_UNAVAILABLE", "Filesystem owner validation requires a POSIX runtime");
  }
  return getuid();
}

function secureFailure(error: unknown, code: string, message: string): never {
  if (error instanceof ManifestContractError) throw error;
  throw new ManifestContractError(code, message, { cause: error });
}

async function inspectManifestSecurity(manifestPath: string): Promise<SecureManifestContext> {
  const absoluteManifest = resolve(manifestPath);
  let runDirectory: SecureDirectoryInspection;
  try {
    runDirectory = await inspectSecureDirectory(dirname(absoluteManifest));
  } catch (error) {
    secureFailure(error, "INSECURE_RUN_DIRECTORY", "Variant run directory must be a private, non-symlinked directory");
  }
  const expectedUid = ownerUid();
  if (runDirectory.mode !== 0o700) {
    throw new ManifestContractError("INSECURE_RUN_DIRECTORY", "Variant run directory permissions must be exactly 0700");
  }
  if (runDirectory.ownerUid !== expectedUid) {
    throw new ManifestContractError("OWNER_MISMATCH", "Variant run directory owner does not match the current user");
  }

  let manifest: ContainedFileSnapshot;
  try {
    manifest = await readContainedFileSnapshot(
      runDirectory.absolutePath,
      basename(absoluteManifest),
      { maximumBytes: MAX_MANIFEST_BYTES },
    );
  } catch (error) {
    if (error instanceof SecureIoError) {
      if (error.code === "FILE_TOO_LARGE") {
        throw new ManifestContractError("MANIFEST_TOO_LARGE", "Variant manifest exceeds the 1 MiB safety limit", {
          cause: error,
        });
      }
      if (error.code === "SYMLINK_REJECTED" || error.code === "PATH_ESCAPE") {
        throw new ManifestContractError("UNSAFE_MANIFEST", "Variant manifest must not be a symlink or escape its run directory", {
          cause: error,
        });
      }
    }
    secureFailure(error, "MANIFEST_NOT_FOUND", "Variant manifest is not a regular file");
  }
  if (manifest.absolutePath !== resolve(runDirectory.absolutePath, basename(absoluteManifest))) {
    throw new ManifestContractError("UNSAFE_MANIFEST", "Variant manifest resolves outside its run directory");
  }
  if (manifest.mode !== 0o600) {
    throw new ManifestContractError("INSECURE_MANIFEST", "Variant manifest permissions must be exactly 0600");
  }
  if (manifest.ownerUid !== expectedUid) {
    throw new ManifestContractError("OWNER_MISMATCH", "Variant manifest owner does not match the current user");
  }
  return Object.freeze({ runDirectory: runDirectory.absolutePath, manifest });
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  return value as Record<string, unknown>;
}

function finiteInteger(value: unknown, label: string, minimum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    throw new ManifestContractError("INVALID_MANIFEST", `${label} must be an integer of at least ${minimum}`);
  }
  return value;
}

function parseEntry(value: unknown, index: number): VariantManifestEntry {
  const record = asRecord(value);
  if (!record) throw new ManifestContractError("INVALID_MANIFEST", `Variant ${index + 1} must be an object`);
  const variant = record.variant;
  if (typeof variant !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(variant)) {
    throw new ManifestContractError("INVALID_MANIFEST", `Variant ${index + 1} has an invalid identifier`);
  }
  if (typeof record.audit_success !== "boolean" || typeof record.pdf_success !== "boolean") {
    throw new ManifestContractError("INVALID_MANIFEST", `Variant ${variant} is missing audit/PDF status`);
  }
  const artifactsRecord = asRecord(record.artifacts);
  if (!artifactsRecord) {
    throw new ManifestContractError("INVALID_MANIFEST", `Variant ${variant} has no artifact map`);
  }
  const artifacts: Record<string, string> = {};
  for (const [key, artifact] of Object.entries(artifactsRecord)) {
    if (typeof artifact !== "string" || !SAFE_ARTIFACT_NAME.test(artifact) || basename(artifact) !== artifact) {
      throw new ManifestContractError("UNSAFE_ARTIFACT", `Variant ${variant} contains an unsafe artifact name`);
    }
    artifacts[key] = artifact;
  }
  const actualPages = record.actual_pages;
  if (actualPages !== null && actualPages !== undefined) {
    finiteInteger(actualPages, `Variant ${variant} actual_pages`, 1);
  }
  return Object.freeze({
    variant,
    targetPages: finiteInteger(record.target_pages, `Variant ${variant} target_pages`, 1),
    ...(actualPages === null || actualPages === undefined ? {} : { actualPages: actualPages as number }),
    auditSuccess: record.audit_success,
    pdfSuccess: record.pdf_success,
    artifacts: Object.freeze(artifacts),
  });
}

export async function readVariantManifest(manifestPath: string): Promise<VariantManifest> {
  const context = await inspectManifestSecurity(manifestPath);
  let parsed: unknown;
  try {
    parsed = JSON.parse(STRICT_UTF8_DECODER.decode(context.manifest.bytes));
  } catch {
    throw new ManifestContractError("MALFORMED_MANIFEST", "Variant manifest is not valid UTF-8 JSON");
  }
  const root = asRecord(parsed);
  if (!root || root.schema_version !== 1 || !Array.isArray(root.variants)) {
    throw new ManifestContractError("INVALID_MANIFEST", "Variant manifest must use schema_version 1 and contain variants");
  }
  if (root.variants.length === 0) {
    throw new ManifestContractError("INVALID_MANIFEST", "Variant manifest contains no variants");
  }
  return Object.freeze({
    schemaVersion: 1,
    variants: Object.freeze(root.variants.map(parseEntry)),
  });
}

export function summarizeVariantManifest(manifest: VariantManifest): ManifestStatusSummary {
  const variants: VariantStatusSummary[] = manifest.variants.map((entry) => Object.freeze({
    variant: entry.variant,
    targetPages: entry.targetPages,
    ...(entry.actualPages === undefined ? {} : { actualPages: entry.actualPages }),
    auditSuccess: entry.auditSuccess,
    pdfSuccess: entry.pdfSuccess,
  }));
  return Object.freeze({
    schemaVersion: manifest.schemaVersion,
    variantCount: variants.length,
    variants: Object.freeze(variants),
  });
}

export async function resolveVariantArtifacts(
  manifestPath: string,
  manifest: VariantManifest,
  kind: VariantArtifactKind,
): Promise<readonly ResolvedVariantArtifact[]> {
  const context = await inspectManifestSecurity(manifestPath);
  const expectedUid = ownerUid();
  const resolved: ResolvedVariantArtifact[] = [];
  for (const entry of manifest.variants) {
    const artifact = entry.artifacts[kind];
    if (!artifact) {
      throw new ManifestContractError("MISSING_ARTIFACT", `Variant ${entry.variant} does not list a ${kind} artifact`);
    }
    if (!SAFE_ARTIFACT_NAME.test(artifact) || isAbsolute(artifact) || basename(artifact) !== artifact) {
      throw new ManifestContractError("UNSAFE_ARTIFACT", `Variant ${entry.variant} contains an unsafe ${kind} artifact`);
    }

    let snapshot: ContainedFileSnapshot;
    try {
      snapshot = await readContainedFileSnapshot(context.runDirectory, artifact);
    } catch (error) {
      if (error instanceof SecureIoError) {
        if (error.code === "SYMLINK_REJECTED" || error.code === "PATH_ESCAPE") {
          throw new ManifestContractError(
            "UNSAFE_ARTIFACT",
            `Variant ${entry.variant} ${kind} artifact must not be a symlink or escape the run directory`,
            { cause: error },
          );
        }
        if (
          error.code === "NOT_FOUND"
          || error.code === "NOT_REGULAR_FILE"
          || error.code === "NOT_DIRECTORY"
        ) {
          throw new ManifestContractError(
            "MISSING_ARTIFACT",
            `Variant ${entry.variant} ${kind} artifact is missing or not a regular file`,
            { cause: error },
          );
        }
      }
      secureFailure(
        error,
        "INSECURE_ARTIFACT",
        `Variant ${entry.variant} ${kind} artifact could not be securely inspected`,
      );
    }
    if (snapshot.absolutePath !== resolve(context.runDirectory, artifact)) {
      throw new ManifestContractError(
        "UNSAFE_ARTIFACT",
        `Variant ${entry.variant} ${kind} artifact resolves outside the run directory`,
      );
    }
    if (snapshot.mode !== 0o600) {
      throw new ManifestContractError(
        "INSECURE_ARTIFACT",
        `Variant ${entry.variant} ${kind} artifact permissions must be exactly 0600`,
      );
    }
    if (snapshot.ownerUid !== expectedUid) {
      throw new ManifestContractError(
        "OWNER_MISMATCH",
        `Variant ${entry.variant} ${kind} artifact owner does not match the current user`,
      );
    }
    resolved.push(Object.freeze({ variant: entry.variant, path: snapshot.absolutePath }));
  }
  return Object.freeze(resolved);
}
