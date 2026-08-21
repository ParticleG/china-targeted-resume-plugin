import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { realpath, stat } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { createInterface } from "node:readline";
import {
  DEFAULT_MAX_SOURCE_SLICE_BYTES,
  readAuthorizedSourceSlice,
  type RunPrivacyState,
  type SourceSlicePrefilterResult,
  type SourceSliceRequest,
} from "../privacy/index.ts";

export class SourceSliceReadError extends Error {
  readonly code: string;

  constructor(code: string, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "SourceSliceReadError";
    this.code = code;
  }
}

export function relativeSourcePath(repositoryRoot: string, requestedPath: string): string {
  const root = resolve(repositoryRoot);
  const candidate = isAbsolute(requestedPath) ? resolve(requestedPath) : resolve(root, requestedPath);
  const relativePath = relative(root, candidate).replaceAll("\\", "/");
  if (!relativePath || relativePath === ".." || relativePath.startsWith("../")) {
    throw new SourceSliceReadError(
      "SOURCE_SLICE_OUTSIDE_ROOT",
      "Source slice does not resolve inside the authorized source root",
    );
  }
  return relativePath;
}

async function resolveBoundedFile(repositoryRoot: string, requestedPath: string): Promise<string> {
  const root = await realpath(repositoryRoot).catch(() => undefined);
  if (!root) throw new SourceSliceReadError("SOURCE_ROOT_NOT_FOUND", "Source root is not accessible");
  const candidate = isAbsolute(requestedPath) ? requestedPath : resolve(root, requestedPath);
  const resolved = await realpath(candidate).catch(() => undefined);
  const rootPrefix = root.endsWith(sep) ? root : `${root}${sep}`;
  if (!resolved || (!resolved.startsWith(rootPrefix) && resolved !== root)) {
    throw new SourceSliceReadError("SOURCE_SLICE_OUTSIDE_ROOT", "Source slice does not resolve inside the authorized source root");
  }
  const metadata = await stat(resolved);
  if (!metadata.isFile()) throw new SourceSliceReadError("SOURCE_SLICE_NOT_FILE", "Source slice must resolve to a regular file");
  return resolved;
}

async function verifySourceHash(path: string, expected: `sha256:${string}`): Promise<void> {
  const digest = createHash("sha256");
  const input = createReadStream(path);
  try {
    for await (const chunk of input) digest.update(chunk);
  } finally {
    input.destroy();
  }
  if (`sha256:${digest.digest("hex")}` !== expected) {
    throw new SourceSliceReadError(
      "SOURCE_HASH_MISMATCH",
      "Source file changed after source-map validation",
    );
  }
}

async function readLineRange(
  path: string,
  startLine: number,
  endLine: number,
  maxBytes: number,
): Promise<string> {
  const input = createReadStream(path, { encoding: "utf8" });
  const lines = createInterface({ input, crlfDelay: Number.POSITIVE_INFINITY });
  const selected: string[] = [];
  let lineNumber = 0;
  let totalBytes = 0;
  try {
    for await (const line of lines) {
      lineNumber += 1;
      if (lineNumber < startLine) continue;
      if (lineNumber > endLine) break;
      const separatorBytes = selected.length === 0 ? 0 : 1;
      totalBytes += Buffer.byteLength(line, "utf8") + separatorBytes;
      if (totalBytes > maxBytes) {
        throw new SourceSliceReadError("SOURCE_SLICE_TOO_LARGE", "Source slice exceeds its authorized byte limit");
      }
      selected.push(line);
    }
  } catch (cause) {
    if (cause instanceof SourceSliceReadError) throw cause;
    throw new SourceSliceReadError("SOURCE_SLICE_READ_FAILED", "Source slice could not be read as UTF-8", { cause });
  } finally {
    lines.close();
    input.destroy();
  }
  if (lineNumber < startLine || selected.length === 0) {
    throw new SourceSliceReadError("SOURCE_SLICE_RANGE_MISSING", "Authorized line range is outside the source file");
  }
  return selected.join("\n");
}

export interface AuthorizedSliceInput {
  readonly state: RunPrivacyState;
  readonly consumer: SourceSliceRequest["consumer"];
  readonly repositoryRoot: string;
  readonly path: string;
  readonly startLine: number;
  readonly endLine: number;
  readonly category: string;
  readonly authorizationId: string;
  readonly provider: string;
  readonly model: string;
  readonly locality: "local" | "remote";
  readonly purpose: string;
  readonly effectivePolicy: string;
  readonly ancestorPolicies: readonly string[];
  readonly expectedSourceHash: `sha256:${string}`;
  readonly blockedByPolicy: boolean;
  readonly maxBytes?: number;
  readonly requestId?: string;
}

/** Reads only after metadata authorization, bounded path checks, and content prefiltering. */
export async function readPrefilteredSourceSlice(input: AuthorizedSliceInput): Promise<SourceSlicePrefilterResult> {
  const requestedPath = isAbsolute(input.path) ? input.path : resolve(input.repositoryRoot, input.path);
  const request: SourceSliceRequest = {
    consumer: input.consumer,
    repositoryRoot: input.repositoryRoot,
    path: requestedPath,
    startLine: input.startLine,
    endLine: input.endLine,
    category: input.category,
    authorizationId: input.authorizationId,
    provider: input.provider,
    model: input.model,
    purpose: input.purpose,
    effectivePolicy: input.effectivePolicy,
    ancestorPolicies: input.ancestorPolicies,
    locality: input.locality,
    blockedByPolicy: input.blockedByPolicy,
    maxBytes: input.maxBytes ?? DEFAULT_MAX_SOURCE_SLICE_BYTES,
    ...(input.requestId === undefined ? {} : { requestId: input.requestId }),
  };
  return readAuthorizedSourceSlice(input.state, request, async () => {
    const resolved = await resolveBoundedFile(input.repositoryRoot, requestedPath);
    await verifySourceHash(resolved, input.expectedSourceHash);
    return readLineRange(resolved, input.startLine, input.endLine, request.maxBytes ?? DEFAULT_MAX_SOURCE_SLICE_BYTES);
  });
}
