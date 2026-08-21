/**
 * Linux-only, descriptor-anchored output and source I/O. Every traversed
 * component is opened with O_NOFOLLOW and checked against its lstat identity.
 */

import { createHash, randomUUID } from "node:crypto";
import { constants, type BigIntStats } from "node:fs";
import {
  link,
  lstat,
  mkdir,
  open,
  realpath,
  unlink,
  type FileHandle,
} from "node:fs/promises";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  parse,
  relative,
  resolve,
  sep,
} from "node:path";

export const SECURE_IO_ERROR_CODES = [
  "UNSUPPORTED_PLATFORM",
  "INVALID_PATH",
  "PATH_ESCAPE",
  "SYMLINK_REJECTED",
  "NOT_FOUND",
  "NOT_DIRECTORY",
  "NOT_REGULAR_FILE",
  "INSECURE_PERMISSIONS",
  "ALREADY_EXISTS",
  "SOURCE_CHANGED",
  "FILE_TOO_LARGE",
  "IO_FAILURE",
] as const;

export type SecureIoErrorCode = (typeof SECURE_IO_ERROR_CODES)[number];
export type SecureIoDetail = null | boolean | number | string;

export interface SerializedSecureIoError {
  readonly name: "SecureIoError";
  readonly code: SecureIoErrorCode;
  readonly operation: string;
  readonly message: string;
  readonly details: Readonly<Record<string, SecureIoDetail>>;
}

export class SecureIoError extends Error {
  override readonly name = "SecureIoError";
  readonly code: SecureIoErrorCode;
  readonly operation: string;
  readonly details: Readonly<Record<string, SecureIoDetail>>;

  constructor(
    code: SecureIoErrorCode,
    operation: string,
    message: string,
    details: Readonly<Record<string, SecureIoDetail>> = {},
    options: { readonly cause?: unknown } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.code = code;
    this.operation = operation;
    this.details = Object.freeze({ ...details });
  }

  toJSON(): SerializedSecureIoError {
    return Object.freeze({
      name: this.name,
      code: this.code,
      operation: this.operation,
      message: this.message,
      details: this.details,
    });
  }
}

export interface ValidatedOutputRoots {
  readonly sourceRoot: string;
  readonly outputRoot: string;
}

export interface PrivateDirectoryOptions {
  readonly existOk?: boolean;
}

export interface RunDirectoryOptions {
  readonly now?: Date;
  readonly attempts?: number;
}

export interface SecureDirectoryInspection {
  readonly absolutePath: string;
  readonly mode: number;
  readonly ownerUid: number;
  readonly device: bigint;
  readonly inode: bigint;
}

export interface ContainedFileSnapshot {
  readonly absolutePath: string;
  readonly bytes: Uint8Array;
  readonly mode: number;
  readonly ownerUid: number;
  readonly size: number;
  readonly device: bigint;
  readonly inode: bigint;
}

export interface ContainedFileReadOptions {
  readonly maximumBytes?: number;
}

// Node opens descriptors non-inheritable unless a caller explicitly passes a
// descriptor through child_process stdio; @types/node does not expose O_CLOEXEC.
const DIRECTORY_FLAGS = constants.O_RDONLY
  | constants.O_DIRECTORY
  | constants.O_NOFOLLOW;
const REGULAR_FILE_FLAGS = constants.O_RDONLY
  | constants.O_NOFOLLOW
  | constants.O_NONBLOCK;
const PRIVATE_DIRECTORY_MODE = 0o700;
const PRIVATE_FILE_MODE = 0o600;
const MAX_RELATIVE_PATH_LENGTH = 4096;

function nodeCode(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("code" in error)) return undefined;
  const code = error.code;
  return typeof code === "string" ? code : undefined;
}

function mappedIoError(operation: string, path: string, error: unknown): SecureIoError {
  if (error instanceof SecureIoError) return error;
  const causeCode = nodeCode(error);
  const details: Record<string, SecureIoDetail> = { path };
  if (causeCode !== undefined) details.causeCode = causeCode;
  if (causeCode === "ENOENT") {
    return new SecureIoError("NOT_FOUND", operation, `Path does not exist: ${path}`, details, { cause: error });
  }
  if (causeCode === "EEXIST") {
    return new SecureIoError("ALREADY_EXISTS", operation, `Path already exists: ${path}`, details, { cause: error });
  }
  if (causeCode === "ELOOP") {
    return new SecureIoError("SYMLINK_REJECTED", operation, `Symbolic links are forbidden: ${path}`, details, { cause: error });
  }
  return new SecureIoError("IO_FAILURE", operation, `Secure filesystem operation failed for ${path}`, details, {
    cause: error,
  });
}

function requireLinux(operation: string): void {
  if (process.platform !== "linux") {
    throw new SecureIoError(
      "UNSUPPORTED_PLATFORM",
      operation,
      "Secure kernel filesystem primitives require Linux /proc/self/fd and O_NOFOLLOW",
      { platform: process.platform },
    );
  }
}

function absoluteSegments(path: string): readonly string[] {
  const parsed = parse(path);
  if (parsed.root !== sep || !isAbsolute(path)) {
    throw new SecureIoError("INVALID_PATH", "resolve-path", "Path must resolve to an absolute Linux path", {
      path,
    });
  }
  if (path === sep) return [];
  return path.slice(parsed.root.length).split(sep);
}

function procChildPath(directory: FileHandle, name: string): string {
  return `/proc/self/fd/${directory.fd}/${name}`;
}

function sameFileIdentity(left: BigIntStats, right: BigIntStats): boolean {
  return left.dev === right.dev && left.ino === right.ino;
}

function sameFileRevision(left: BigIntStats, right: BigIntStats): boolean {
  return sameFileIdentity(left, right)
    && left.size === right.size
    && left.mtimeNs === right.mtimeNs
    && left.ctimeNs === right.ctimeNs;
}

async function closeQuietly(handle: FileHandle | undefined): Promise<void> {
  if (handle === undefined) return;
  try {
    await handle.close();
  } catch {
    // Preserve the primary filesystem error.
  }
}

async function openDirectoryChain(absolutePath: string, operation: string): Promise<FileHandle> {
  requireLinux(operation);
  let current: FileHandle | undefined;
  try {
    current = await open(sep, DIRECTORY_FLAGS);
    let traversed: string = sep;
    for (const segment of absoluteSegments(absolutePath)) {
      const childPath = procChildPath(current, segment);
      const visiblePath = join(traversed, segment);
      const before = await lstat(childPath, { bigint: true });
      if (before.isSymbolicLink()) {
        throw new SecureIoError(
          "SYMLINK_REJECTED",
          operation,
          `Directory chain contains a symbolic link: ${visiblePath}`,
          { path: visiblePath },
        );
      }
      if (!before.isDirectory()) {
        throw new SecureIoError("NOT_DIRECTORY", operation, `Path component is not a directory: ${visiblePath}`, {
          path: visiblePath,
        });
      }
      const next = await open(childPath, DIRECTORY_FLAGS);
      const opened = await next.stat({ bigint: true });
      if (!opened.isDirectory() || !sameFileIdentity(before, opened)) {
        await closeQuietly(next);
        throw new SecureIoError(
          "SOURCE_CHANGED",
          operation,
          `Directory component changed during secure traversal: ${visiblePath}`,
          { path: visiblePath },
        );
      }
      await closeQuietly(current);
      current = next;
      traversed = visiblePath;
    }
    const result = current;
    current = undefined;
    return result;
  } catch (error) {
    await closeQuietly(current);
    throw mappedIoError(operation, absolutePath, error);
  }
}

export function validateRelativePath(path: string): string {
  let characterCount = 0;
  for (const _character of path) characterCount += 1;
  if (
    characterCount === 0
    || characterCount > MAX_RELATIVE_PATH_LENGTH
    || path.includes("\0")
    || path.includes("\\")
    || path.startsWith("/")
  ) {
    throw new SecureIoError("INVALID_PATH", "validate-relative-path", "Source path must be a canonical POSIX-relative path", {
      path,
    });
  }
  const segments = path.split("/");
  if (segments.some((segment) => segment.length === 0 || segment === "." || segment === "..")) {
    throw new SecureIoError(
      "INVALID_PATH",
      "validate-relative-path",
      "Source path must not contain empty, current-directory, or parent-directory segments",
      { path },
    );
  }
  return path;
}

function pathIsWithin(root: string, candidate: string): boolean {
  const difference = relative(root, candidate);
  return difference === ""
    || (difference !== ".." && !difference.startsWith(`..${sep}`) && !isAbsolute(difference));
}

interface OpenContainedEntry {
  readonly absolutePath: string;
  readonly handle: FileHandle;
  readonly revision: BigIntStats;
}

async function openContainedEntry(
  root: string,
  relativePath: string,
  kind: "directory" | "file",
  operation: string,
): Promise<OpenContainedEntry> {
  const normalizedPath = validateRelativePath(relativePath);
  const absoluteRoot = resolve(root);
  const absolutePath = join(absoluteRoot, ...normalizedPath.split("/"));
  if (!pathIsWithin(absoluteRoot, absolutePath)) {
    throw new SecureIoError("PATH_ESCAPE", operation, "Path escapes its canonical root", {
      root: absoluteRoot,
      path: normalizedPath,
    });
  }

  let current: FileHandle | undefined;
  try {
    current = await openDirectoryChain(absoluteRoot, operation);
    const segments = normalizedPath.split("/");
    for (const [index, segment] of segments.entries()) {
      const final = index === segments.length - 1;
      const expectedDirectory = !final || kind === "directory";
      const childPath = procChildPath(current, segment);
      const before = await lstat(childPath, { bigint: true });
      if (before.isSymbolicLink()) {
        throw new SecureIoError(
          "SYMLINK_REJECTED",
          operation,
          `Contained path includes a symbolic link: ${normalizedPath}`,
          { root: absoluteRoot, path: normalizedPath },
        );
      }
      if (expectedDirectory ? !before.isDirectory() : !before.isFile()) {
        const code = expectedDirectory ? "NOT_DIRECTORY" : "NOT_REGULAR_FILE";
        throw new SecureIoError(code, operation, `Contained path has the wrong filesystem type: ${normalizedPath}`, {
          root: absoluteRoot,
          path: normalizedPath,
        });
      }

      const flags = expectedDirectory ? DIRECTORY_FLAGS : REGULAR_FILE_FLAGS;
      const next = await open(childPath, flags);
      const opened = await next.stat({ bigint: true });
      const correctType = expectedDirectory ? opened.isDirectory() : opened.isFile();
      if (!correctType || !sameFileIdentity(before, opened)) {
        await closeQuietly(next);
        throw new SecureIoError(
          "SOURCE_CHANGED",
          operation,
          `Contained path changed during secure traversal: ${normalizedPath}`,
          { root: absoluteRoot, path: normalizedPath },
        );
      }
      await closeQuietly(current);
      current = next;
    }
    const handle = current;
    current = undefined;
    return { absolutePath, handle, revision: await handle.stat({ bigint: true }) };
  } catch (error) {
    await closeQuietly(current);
    throw mappedIoError(operation, absolutePath, error);
  }
}

export async function resolveContainedPath(
  root: string,
  relativePath: string,
  kind: "directory" | "file" = "file",
): Promise<string> {
  const entry = await openContainedEntry(root, relativePath, kind, "resolve-contained-path");
  await closeQuietly(entry.handle);
  return entry.absolutePath;
}

export async function inspectSecureDirectory(path: string): Promise<SecureDirectoryInspection> {
  const operation = "inspect-secure-directory";
  const absolutePath = resolve(path);
  const handle = await openDirectoryChain(absolutePath, operation);
  try {
    const metadata = await handle.stat({ bigint: true });
    const canonicalPath = await realpath(`/proc/self/fd/${handle.fd}`);
    return Object.freeze({
      absolutePath: canonicalPath,
      mode: Number(metadata.mode) & 0o777,
      ownerUid: Number(metadata.uid),
      device: metadata.dev,
      inode: metadata.ino,
    });
  } catch (error) {
    throw mappedIoError(operation, absolutePath, error);
  } finally {
    await closeQuietly(handle);
  }
}

export async function readContainedFileSnapshot(
  root: string,
  relativePath: string,
  options: ContainedFileReadOptions = {},
): Promise<ContainedFileSnapshot> {
  const operation = "read-contained-file";
  const maximumBytes = options.maximumBytes;
  if (maximumBytes !== undefined && (!Number.isSafeInteger(maximumBytes) || maximumBytes < 0)) {
    throw new SecureIoError("INVALID_PATH", operation, "maximumBytes must be a non-negative safe integer", {
      maximumBytes,
    });
  }
  const entry = await openContainedEntry(root, relativePath, "file", operation);
  try {
    if (maximumBytes !== undefined && entry.revision.size > BigInt(maximumBytes)) {
      throw new SecureIoError(
        "FILE_TOO_LARGE",
        operation,
        `Contained file exceeds the ${maximumBytes}-byte safety limit`,
        { path: relativePath, maximumBytes },
      );
    }
    const data = await entry.handle.readFile();
    const after = await entry.handle.stat({ bigint: true });
    if (!sameFileRevision(entry.revision, after)) {
      throw new SecureIoError(
        "SOURCE_CHANGED",
        operation,
        `Contained file changed while it was being read: ${relativePath}`,
        { root: resolve(root), path: relativePath },
      );
    }
    return Object.freeze({
      absolutePath: entry.absolutePath,
      bytes: data,
      mode: Number(after.mode) & 0o777,
      ownerUid: Number(after.uid),
      size: data.byteLength,
      device: after.dev,
      inode: after.ino,
    });
  } catch (error) {
    throw mappedIoError(operation, entry.absolutePath, error);
  } finally {
    await closeQuietly(entry.handle);
  }
}

export async function readContainedFile(root: string, relativePath: string): Promise<Uint8Array> {
  return (await readContainedFileSnapshot(root, relativePath)).bytes;
}

async function inspectPotentialPath(absolutePath: string, operation: string): Promise<void> {
  requireLinux(operation);
  let current: FileHandle | undefined;
  try {
    current = await open(sep, DIRECTORY_FLAGS);
    const segments = absoluteSegments(absolutePath);
    for (const [index, segment] of segments.entries()) {
      const final = index === segments.length - 1;
      const childPath = procChildPath(current, segment);
      let before: BigIntStats;
      try {
        before = await lstat(childPath, { bigint: true });
      } catch (error) {
        if (nodeCode(error) === "ENOENT") return;
        throw error;
      }
      if (before.isSymbolicLink()) {
        throw new SecureIoError(
          "SYMLINK_REJECTED",
          operation,
          `Path chain contains a symbolic link: ${absolutePath}`,
          { path: absolutePath },
        );
      }
      if (final) return;
      if (!before.isDirectory()) {
        throw new SecureIoError("NOT_DIRECTORY", operation, `Path component is not a directory: ${absolutePath}`, {
          path: absolutePath,
        });
      }
      const next = await open(childPath, DIRECTORY_FLAGS);
      const opened = await next.stat({ bigint: true });
      if (!opened.isDirectory() || !sameFileIdentity(before, opened)) {
        await closeQuietly(next);
        throw new SecureIoError("SOURCE_CHANGED", operation, `Path changed during secure traversal: ${absolutePath}`, {
          path: absolutePath,
        });
      }
      await closeQuietly(current);
      current = next;
    }
  } catch (error) {
    throw mappedIoError(operation, absolutePath, error);
  } finally {
    await closeQuietly(current);
  }
}

export async function validateOutputRoot(sourceRoot: string, outputRoot: string): Promise<ValidatedOutputRoots> {
  const source = resolve(sourceRoot);
  const sourceHandle = await openDirectoryChain(source, "validate-output-root");
  let canonicalSource: string;
  try {
    canonicalSource = await realpath(`/proc/self/fd/${sourceHandle.fd}`);
  } catch (error) {
    throw mappedIoError("validate-output-root", source, error);
  } finally {
    await closeQuietly(sourceHandle);
  }
  const output = resolve(outputRoot);
  await inspectPotentialPath(output, "validate-output-root");
  if (pathIsWithin(canonicalSource, output)) {
    throw new SecureIoError(
      "PATH_ESCAPE",
      "validate-output-root",
      "Output root must be outside the read-only source root",
      { sourceRoot: canonicalSource, outputRoot: output },
    );
  }
  return Object.freeze({ sourceRoot: canonicalSource, outputRoot: output });
}

export async function ensurePrivateDirectory(
  path: string,
  options: PrivateDirectoryOptions = {},
): Promise<string> {
  const operation = "ensure-private-directory";
  requireLinux(operation);
  const absolutePath = resolve(path);
  if (absolutePath === sep) {
    throw new SecureIoError("INVALID_PATH", operation, "The filesystem root cannot be used as a private output directory", {
      path: absolutePath,
    });
  }
  const existOk = options.existOk ?? true;
  let current: FileHandle | undefined;
  try {
    current = await open(sep, DIRECTORY_FLAGS);
    const segments = absoluteSegments(absolutePath);
    for (const [index, segment] of segments.entries()) {
      const final = index === segments.length - 1;
      const childPath = procChildPath(current, segment);
      let before: BigIntStats;
      let created = false;
      try {
        before = await lstat(childPath, { bigint: true });
      } catch (error) {
        if (nodeCode(error) !== "ENOENT") throw error;
        try {
          await mkdir(childPath, { mode: PRIVATE_DIRECTORY_MODE });
          await current.sync();
          created = true;
        } catch (mkdirError) {
          if (nodeCode(mkdirError) !== "EEXIST") throw mkdirError;
        }
        before = await lstat(childPath, { bigint: true });
      }

      if (before.isSymbolicLink()) {
        throw new SecureIoError(
          "SYMLINK_REJECTED",
          operation,
          `Private directory chain contains a symbolic link: ${absolutePath}`,
          { path: absolutePath },
        );
      }
      if (!before.isDirectory()) {
        throw new SecureIoError("NOT_DIRECTORY", operation, `Private directory path is not a directory: ${absolutePath}`, {
          path: absolutePath,
        });
      }
      if (final && !created && !existOk) {
        throw new SecureIoError("ALREADY_EXISTS", operation, `Private directory already exists: ${absolutePath}`, {
          path: absolutePath,
        });
      }

      const next = await open(childPath, DIRECTORY_FLAGS);
      const opened = await next.stat({ bigint: true });
      if (!opened.isDirectory() || !sameFileIdentity(before, opened)) {
        await closeQuietly(next);
        throw new SecureIoError("SOURCE_CHANGED", operation, `Directory changed during creation: ${absolutePath}`, {
          path: absolutePath,
        });
      }
      if (created) {
        await next.chmod(PRIVATE_DIRECTORY_MODE);
      } else if (final && (Number(opened.mode) & 0o077) !== 0) {
        await closeQuietly(next);
        throw new SecureIoError(
          "INSECURE_PERMISSIONS",
          operation,
          `Existing private directory permissions must be 0700 or stricter: ${absolutePath}`,
          { path: absolutePath, mode: Number(opened.mode) & 0o777 },
        );
      }
      if (final) {
        await next.chmod(PRIVATE_DIRECTORY_MODE);
        const secured = await next.stat({ bigint: true });
        if ((Number(secured.mode) & 0o777) !== PRIVATE_DIRECTORY_MODE) {
          await closeQuietly(next);
          throw new SecureIoError("INSECURE_PERMISSIONS", operation, `Could not enforce 0700 permissions: ${absolutePath}`, {
            path: absolutePath,
            mode: Number(secured.mode) & 0o777,
          });
        }
      }
      await closeQuietly(current);
      current = next;
    }
    await closeQuietly(current);
    current = undefined;
    return absolutePath;
  } catch (error) {
    throw mappedIoError(operation, absolutePath, error);
  } finally {
    await closeQuietly(current);
  }
}

function asciiSlug(value: string | null | undefined, fallback: string): string {
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(fallback)) {
    throw new SecureIoError("INVALID_PATH", "slug", "Slug fallback must contain only lowercase ASCII letters, digits, and hyphens", {
      fallback,
    });
  }
  let ascii = "";
  for (const character of (value ?? "").normalize("NFKD")) {
    const codePoint = character.codePointAt(0);
    if (codePoint !== undefined && codePoint <= 0x7f) ascii += character;
  }
  const normalized = ascii.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (normalized.length > 0) return normalized.slice(0, 64).replace(/-+$/g, "");
  if (value) {
    const digest = createHash("sha256").update(value, "utf8").digest("hex").slice(0, 10);
    return `${fallback}-${digest}`;
  }
  return fallback;
}

export function slug(value: string | null | undefined, fallback = "target"): string {
  return asciiSlug(value, fallback);
}

function timestampForRun(now: Date): string {
  if (!Number.isFinite(now.getTime())) {
    throw new SecureIoError("INVALID_PATH", "create-run-directory", "Run timestamp must be a valid Date");
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z$/.exec(now.toISOString());
  if (match === null) {
    throw new SecureIoError("IO_FAILURE", "create-run-directory", "Could not format the UTC run timestamp");
  }
  return `${match[1]}${match[2]}${match[3]}T${match[4]}${match[5]}${match[6]}${match[7]}000Z`;
}

export async function createRunDirectory(
  outputRoot: string,
  company: string | null | undefined,
  role: string | null | undefined,
  options: RunDirectoryOptions = {},
): Promise<string> {
  const root = await ensurePrivateDirectory(outputRoot);
  const prefix = `${asciiSlug(company, "company")}--${asciiSlug(role, "role")}`;
  const timestamp = timestampForRun(options.now ?? new Date());
  const attempts = options.attempts ?? 1000;
  if (!Number.isSafeInteger(attempts) || attempts < 1 || attempts > 1000) {
    throw new SecureIoError("INVALID_PATH", "create-run-directory", "Run allocation attempts must be an integer from 1 through 1000", {
      attempts,
    });
  }
  for (let sequence = 0; sequence < attempts; sequence += 1) {
    const suffix = sequence === 0 ? "" : `-${sequence.toString().padStart(3, "0")}`;
    const candidate = join(root, `${prefix}--${timestamp}${suffix}`);
    try {
      return await ensurePrivateDirectory(candidate, { existOk: false });
    } catch (error) {
      if (error instanceof SecureIoError && error.code === "ALREADY_EXISTS") continue;
      throw error;
    }
  }
  throw new SecureIoError(
    "ALREADY_EXISTS",
    "create-run-directory",
    "Could not allocate a timestamped non-overwriting run directory",
    { outputRoot: root, attempts },
  );
}

export async function atomicWriteFileNoReplace(
  path: string,
  data: string | Uint8Array,
): Promise<string> {
  const operation = "atomic-write-file-no-replace";
  requireLinux(operation);
  const destination = resolve(path);
  if (destination === sep) {
    throw new SecureIoError("INVALID_PATH", operation, "The filesystem root cannot be a file destination", {
      path: destination,
    });
  }
  const parent = await ensurePrivateDirectory(dirname(destination));
  const directory = await openDirectoryChain(parent, operation);
  const name = basename(destination);
  const destinationPath = procChildPath(directory, name);
  const temporaryName = `.ctr-${process.pid}-${randomUUID()}.tmp`;
  const temporaryPath = procChildPath(directory, temporaryName);
  let temporary: FileHandle | undefined;
  let temporaryExists = false;
  try {
    try {
      const existing = await lstat(destinationPath, { bigint: true });
      if (existing.isSymbolicLink()) {
        throw new SecureIoError("SYMLINK_REJECTED", operation, `Refusing to write through a symbolic link: ${destination}`, {
          path: destination,
        });
      }
      throw new SecureIoError("ALREADY_EXISTS", operation, `Refusing to overwrite existing path: ${destination}`, {
        path: destination,
      });
    } catch (error) {
      if (nodeCode(error) !== "ENOENT") throw error;
    }

    temporary = await open(
      temporaryPath,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
      PRIVATE_FILE_MODE,
    );
    temporaryExists = true;
    await temporary.chmod(PRIVATE_FILE_MODE);
    await temporary.writeFile(data);
    await temporary.sync();
    await temporary.close();
    temporary = undefined;

    await link(temporaryPath, destinationPath);
    await unlink(temporaryPath);
    temporaryExists = false;
    await directory.sync();

    const written = await lstat(destinationPath, { bigint: true });
    if (!written.isFile() || (Number(written.mode) & 0o777) !== PRIVATE_FILE_MODE) {
      throw new SecureIoError(
        "INSECURE_PERMISSIONS",
        operation,
        `Atomic destination is not a private 0600 regular file: ${destination}`,
        { path: destination, mode: Number(written.mode) & 0o777 },
      );
    }
    return destination;
  } catch (error) {
    await closeQuietly(temporary);
    if (temporaryExists) {
      try {
        await unlink(temporaryPath);
      } catch {
        // Best-effort cleanup cannot replace the primary error.
      }
    }
    throw mappedIoError(operation, destination, error);
  } finally {
    await closeQuietly(directory);
  }
}

export async function atomicWriteContainedFileNoReplace(
  outputRoot: string,
  relativePath: string,
  data: string | Uint8Array,
): Promise<string> {
  const normalizedPath = validateRelativePath(relativePath);
  const root = await ensurePrivateDirectory(outputRoot);
  const destination = join(root, ...normalizedPath.split("/"));
  if (!pathIsWithin(root, destination)) {
    throw new SecureIoError("PATH_ESCAPE", "atomic-write-contained-file-no-replace", "Output path escapes its root", {
      root,
      path: normalizedPath,
    });
  }
  return atomicWriteFileNoReplace(destination, data);
}

function compareUnicodeCodePoints(left: string, right: string): number {
  const leftIterator = left[Symbol.iterator]();
  const rightIterator = right[Symbol.iterator]();
  while (true) {
    const leftPart = leftIterator.next();
    const rightPart = rightIterator.next();
    if (leftPart.done || rightPart.done) {
      if (leftPart.done && rightPart.done) return 0;
      return leftPart.done ? -1 : 1;
    }
    const difference = (leftPart.value.codePointAt(0) ?? 0) - (rightPart.value.codePointAt(0) ?? 0);
    if (difference !== 0) return difference;
  }
}

function canonicalJsonValue(value: unknown, ancestors: Set<object>, path: string): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (Number.isFinite(value)) return value;
    throw new SecureIoError("INVALID_PATH", "canonical-json", `JSON number must be finite at ${path}`);
  }
  if (typeof value !== "object") {
    throw new SecureIoError("INVALID_PATH", "canonical-json", `Value is not JSON-compatible at ${path}`);
  }
  if (ancestors.has(value)) {
    throw new SecureIoError("INVALID_PATH", "canonical-json", `JSON value contains a reference cycle at ${path}`);
  }
  const prototype = Object.getPrototypeOf(value);
  if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) {
    throw new SecureIoError("INVALID_PATH", "canonical-json", `JSON object must have a plain prototype at ${path}`);
  }
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return value.map((nested, index) => canonicalJsonValue(nested, ancestors, `${path}[${index}]`));
    }
    const normalized: Record<string, unknown> = {};
    const entries = Object.entries(value).sort(([left], [right]) => compareUnicodeCodePoints(left, right));
    for (const [key, nested] of entries) {
      normalized[key] = canonicalJsonValue(nested, ancestors, `${path}.${key}`);
    }
    return normalized;
  } finally {
    ancestors.delete(value);
  }
}

export function canonicalJsonText(value: unknown): string {
  return `${JSON.stringify(canonicalJsonValue(value, new Set(), "$root"), null, 2)}\n`;
}

export async function atomicWriteJsonNoReplace(path: string, value: unknown): Promise<string> {
  return atomicWriteFileNoReplace(path, canonicalJsonText(value));
}
