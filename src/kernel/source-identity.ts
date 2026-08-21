/**
 * Exact-byte source identity only. Markdown ownership, structural flags, and
 * evidence semantics remain parser-backed Python boundaries.
 */

import { createHash, timingSafeEqual } from "node:crypto";
import { Buffer } from "node:buffer";
import { readContainedFile, validateRelativePath } from "./secure-io.ts";

export type SourceHash = `sha256:${string}`;

export interface SourceIdentity {
  readonly path: string;
  readonly source_hash: SourceHash;
}

export interface SourceSnapshot extends SourceIdentity {
  readonly byte_length: number;
  /** Returns an isolated copy so source_hash can never disagree with snapshot state. */
  copyBytes(): Uint8Array;
}

export interface SourceSpan {
  readonly start_line: number;
  readonly end_line: number;
  readonly start_byte: number;
  readonly end_byte: number;
}

export interface ExactSourceReference extends SourceIdentity {
  readonly span: SourceSpan;
  readonly exact_quote: string;
}

export const SOURCE_IDENTITY_ERROR_CODES = [
  "INVALID_SOURCE_HASH",
  "SOURCE_CHANGED",
  "INVALID_SPAN",
  "INVALID_UTF8",
  "QUOTE_MISMATCH",
] as const;

export type SourceIdentityErrorCode = (typeof SOURCE_IDENTITY_ERROR_CODES)[number];
export type SourceIdentityDetail = null | boolean | number | string;

export interface SerializedSourceIdentityError {
  readonly name: "SourceIdentityError";
  readonly code: SourceIdentityErrorCode;
  readonly operation: string;
  readonly message: string;
  readonly details: Readonly<Record<string, SourceIdentityDetail>>;
}

export class SourceIdentityError extends Error {
  override readonly name = "SourceIdentityError";
  readonly code: SourceIdentityErrorCode;
  readonly operation: string;
  readonly details: Readonly<Record<string, SourceIdentityDetail>>;

  constructor(
    code: SourceIdentityErrorCode,
    operation: string,
    message: string,
    details: Readonly<Record<string, SourceIdentityDetail>> = {},
    options: { readonly cause?: unknown } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.code = code;
    this.operation = operation;
    this.details = Object.freeze({ ...details });
  }

  toJSON(): SerializedSourceIdentityError {
    return Object.freeze({
      name: this.name,
      code: this.code,
      operation: this.operation,
      message: this.message,
      details: this.details,
    });
  }
}

const SOURCE_HASH_PATTERN = /^sha256:[0-9a-f]{64}$/;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

export function sha256Bytes(bytes: Uint8Array): SourceHash {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

export function sha256Utf8(text: string): SourceHash {
  return `sha256:${createHash("sha256").update(text, "utf8").digest("hex")}`;
}

export function validateSourceHash(value: string): SourceHash {
  if (!SOURCE_HASH_PATTERN.test(value)) {
    throw new SourceIdentityError(
      "INVALID_SOURCE_HASH",
      "validate-source-hash",
      "Source hash must use the canonical sha256:<64 lowercase hex> form",
      { sourceHash: value },
    );
  }
  return value as SourceHash;
}

function hashesEqual(left: SourceHash, right: SourceHash): boolean {
  const leftBytes = Buffer.from(left.slice("sha256:".length), "hex");
  const rightBytes = Buffer.from(right.slice("sha256:".length), "hex");
  return leftBytes.byteLength === rightBytes.byteLength && timingSafeEqual(leftBytes, rightBytes);
}

export function assertSourceIdentity(expected: SourceIdentity, actual: SourceIdentity): void {
  const expectedPath = validateRelativePath(expected.path);
  const actualPath = validateRelativePath(actual.path);
  const expectedHash = validateSourceHash(expected.source_hash);
  const actualHash = validateSourceHash(actual.source_hash);
  if (expectedPath !== actualPath || !hashesEqual(expectedHash, actualHash)) {
    throw new SourceIdentityError(
      "SOURCE_CHANGED",
      "assert-source-identity",
      `Source identity changed for ${expectedPath}`,
      {
        expectedPath,
        actualPath,
        expectedHash,
        actualHash,
      },
    );
  }
}

class ImmutableSourceSnapshot implements SourceSnapshot {
  readonly path: string;
  readonly source_hash: SourceHash;
  readonly byte_length: number;
  readonly #bytes: Uint8Array;

  constructor(path: string, bytes: Uint8Array) {
    this.path = path;
    this.#bytes = Uint8Array.from(bytes);
    this.source_hash = sha256Bytes(this.#bytes);
    this.byte_length = this.#bytes.byteLength;
    Object.freeze(this);
  }

  copyBytes(): Uint8Array {
    return Uint8Array.from(this.#bytes);
  }

  static exactBytes(snapshot: ImmutableSourceSnapshot): Uint8Array {
    return snapshot.#bytes;
  }
}

async function readImmutableSourceSnapshot(
  sourceRoot: string,
  relativePath: string,
): Promise<ImmutableSourceSnapshot> {
  const path = validateRelativePath(relativePath);
  return new ImmutableSourceSnapshot(path, await readContainedFile(sourceRoot, path));
}

export async function readSourceSnapshot(sourceRoot: string, relativePath: string): Promise<SourceSnapshot> {
  return readImmutableSourceSnapshot(sourceRoot, relativePath);
}

export async function captureSourceIdentity(sourceRoot: string, relativePath: string): Promise<SourceIdentity> {
  const snapshot = await readImmutableSourceSnapshot(sourceRoot, relativePath);
  return Object.freeze({ path: snapshot.path, source_hash: snapshot.source_hash });
}

export async function revalidateSourceIdentity(
  sourceRoot: string,
  expected: SourceIdentity,
): Promise<SourceIdentity> {
  const path = validateRelativePath(expected.path);
  const expectedHash = validateSourceHash(expected.source_hash);
  const actual = await captureSourceIdentity(sourceRoot, path);
  assertSourceIdentity({ path, source_hash: expectedHash }, actual);
  return actual;
}

function assertInteger(value: number, name: keyof SourceSpan): void {
  if (!Number.isSafeInteger(value)) {
    throw new SourceIdentityError("INVALID_SPAN", "revalidate-source-span", `${name} must be a safe integer`, {
      field: name,
      value,
    });
  }
}

function lineForByte(bytes: Uint8Array, offset: number): number {
  let line = 1;
  for (let index = 0; index < offset; index += 1) {
    if (bytes[index] === 0x0a) line += 1;
  }
  return line;
}

function decodeSpan(bytes: Uint8Array, span: SourceSpan): string {
  try {
    return UTF8_DECODER.decode(bytes.subarray(span.start_byte, span.end_byte));
  } catch (cause) {
    throw new SourceIdentityError(
      "INVALID_UTF8",
      "revalidate-source-span",
      "Source byte span is not valid UTF-8 or cuts through a UTF-8 code point",
      {
        startByte: span.start_byte,
        endByte: span.end_byte,
      },
      { cause },
    );
  }
}

export function revalidateSourceSpan(bytes: Uint8Array, span: SourceSpan): string {
  assertInteger(span.start_line, "start_line");
  assertInteger(span.end_line, "end_line");
  assertInteger(span.start_byte, "start_byte");
  assertInteger(span.end_byte, "end_byte");
  if (
    span.start_line < 1
    || span.end_line < span.start_line
    || span.start_byte < 0
    || span.end_byte <= span.start_byte
    || span.end_byte > bytes.byteLength
  ) {
    throw new SourceIdentityError(
      "INVALID_SPAN",
      "revalidate-source-span",
      "Source span must be an ordered inclusive line range and half-open byte range within the source",
      {
        sourceLength: bytes.byteLength,
        startLine: span.start_line,
        endLine: span.end_line,
        startByte: span.start_byte,
        endByte: span.end_byte,
      },
    );
  }
  const expectedStartLine = lineForByte(bytes, span.start_byte);
  const expectedEndLine = lineForByte(bytes, Math.max(span.start_byte, span.end_byte - 1));
  if (span.start_line !== expectedStartLine || span.end_line !== expectedEndLine) {
    throw new SourceIdentityError(
      "INVALID_SPAN",
      "revalidate-source-span",
      `Source line span disagrees with UTF-8 byte span; expected ${expectedStartLine}:${expectedEndLine}`,
      {
        startLine: span.start_line,
        endLine: span.end_line,
        expectedStartLine,
        expectedEndLine,
        startByte: span.start_byte,
        endByte: span.end_byte,
      },
    );
  }
  return decodeSpan(bytes, span);
}

export function sourceSpanFromBytes(
  bytes: Uint8Array,
  startByte: number,
  endByte: number,
): SourceSpan {
  assertInteger(startByte, "start_byte");
  assertInteger(endByte, "end_byte");
  if (startByte < 0 || endByte <= startByte || endByte > bytes.byteLength) {
    throw new SourceIdentityError(
      "INVALID_SPAN",
      "source-span-from-bytes",
      "Byte range must be ordered, non-empty, and contained in the source",
      { sourceLength: bytes.byteLength, startByte, endByte },
    );
  }
  const span = Object.freeze({
    start_line: lineForByte(bytes, startByte),
    end_line: lineForByte(bytes, Math.max(startByte, endByte - 1)),
    start_byte: startByte,
    end_byte: endByte,
  });
  revalidateSourceSpan(bytes, span);
  return span;
}

export function revalidateExactQuote(
  bytes: Uint8Array,
  span: SourceSpan,
  exactQuote: string,
): string {
  const actual = revalidateSourceSpan(bytes, span);
  if (actual !== exactQuote) {
    throw new SourceIdentityError(
      "QUOTE_MISMATCH",
      "revalidate-exact-quote",
      "Exact quote does not match source bytes at the declared span",
      {
        startByte: span.start_byte,
        endByte: span.end_byte,
      },
    );
  }
  return actual;
}

export async function revalidateSourceReference(
  sourceRoot: string,
  reference: ExactSourceReference,
): Promise<SourceIdentity> {
  const path = validateRelativePath(reference.path);
  const expectedHash = validateSourceHash(reference.source_hash);
  const snapshot = await readImmutableSourceSnapshot(sourceRoot, path);
  assertSourceIdentity({ path, source_hash: expectedHash }, snapshot);
  revalidateExactQuote(
    ImmutableSourceSnapshot.exactBytes(snapshot),
    reference.span,
    reference.exact_quote,
  );
  return Object.freeze({ path: snapshot.path, source_hash: snapshot.source_hash });
}
