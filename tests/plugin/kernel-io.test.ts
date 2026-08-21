import { afterEach, describe, expect, test } from "bun:test";
import { Buffer } from "node:buffer";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  stat,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import {
  SecureIoError,
  atomicWriteContainedFileNoReplace,
  atomicWriteFileNoReplace,
  atomicWriteJsonNoReplace,
  createRunDirectory,
  ensurePrivateDirectory,
  readContainedFile,
  resolveContainedPath,
  validateOutputRoot,
} from "../../src/kernel/secure-io.ts";
import {
  SourceIdentityError,
  captureSourceIdentity,
  readSourceSnapshot,
  revalidateExactQuote,
  revalidateSourceIdentity,
  revalidateSourceReference,
  revalidateSourceSpan,
  sha256Utf8,
  sourceSpanFromBytes,
} from "../../src/kernel/source-identity.ts";

const temporaryDirectories: string[] = [];

async function privateTemporaryRoot(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "ctr-kernel-test-"));
  temporaryDirectories.push(root);
  await chmod(root, 0o700);
  return root;
}

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

describe("Linux-safe canonical containment", () => {
  test("rejects traversal, final symlinks, symlinked parents, and a symlinked source root", async () => {
    const root = await privateTemporaryRoot();
    const source = join(root, "source");
    const outside = join(root, "outside");
    await mkdir(join(source, "safe"), { recursive: true, mode: 0o700 });
    await mkdir(outside, { mode: 0o700 });
    await writeFile(join(source, "safe", "note.md"), "inside", { mode: 0o600 });
    await writeFile(join(outside, "escape.md"), "outside", { mode: 0o600 });
    await symlink(outside, join(source, "linked-parent"), "dir");
    await symlink(join(outside, "escape.md"), join(source, "linked-file.md"), "file");
    const sourceAlias = join(root, "source-alias");
    await symlink(source, sourceAlias, "dir");

    expect(await resolveContainedPath(source, "safe/note.md")).toBe(join(source, "safe", "note.md"));
    expect(new TextDecoder().decode(await readContainedFile(source, "safe/note.md"))).toBe("inside");
    await expect(readContainedFile(source, "../outside/escape.md")).rejects.toMatchObject({
      name: "SecureIoError",
      code: "INVALID_PATH",
    });
    await expect(readContainedFile(source, "linked-parent/escape.md")).rejects.toMatchObject({
      code: "SYMLINK_REJECTED",
    });
    await expect(readContainedFile(source, "linked-file.md")).rejects.toMatchObject({
      code: "SYMLINK_REJECTED",
    });
    await expect(readContainedFile(sourceAlias, "safe/note.md")).rejects.toMatchObject({
      code: "SYMLINK_REJECTED",
    });
  });

  test("keeps output outside source and rejects a symlink in a prospective output chain", async () => {
    const root = await privateTemporaryRoot();
    const source = join(root, "source");
    const outside = join(root, "outside");
    await mkdir(source, { mode: 0o700 });
    await mkdir(outside, { mode: 0o700 });

    await expect(validateOutputRoot(source, join(source, "generated"))).rejects.toMatchObject({
      code: "PATH_ESCAPE",
    });
    expect(await validateOutputRoot(source, outside)).toEqual({
      sourceRoot: source,
      outputRoot: outside,
    });

    const linkedOutput = join(root, "linked-output");
    await symlink(outside, linkedOutput, "dir");
    await expect(validateOutputRoot(source, join(linkedOutput, "runs"))).rejects.toMatchObject({
      code: "SYMLINK_REJECTED",
    });
  });
});

describe("private atomic non-overwriting output", () => {
  test("creates 0700 directories and a 0600 atomically linked file without leftovers", async () => {
    const root = await privateTemporaryRoot();
    const output = join(root, "output");
    const destination = await atomicWriteContainedFileNoReplace(output, "run/artifact.txt", "first\n");

    expect(Number((await stat(output, { bigint: true })).mode) & 0o777).toBe(0o700);
    expect(Number((await stat(dirname(destination), { bigint: true })).mode) & 0o777).toBe(0o700);
    expect(Number((await stat(destination, { bigint: true })).mode) & 0o777).toBe(0o600);
    expect(await readFile(destination, "utf8")).toBe("first\n");
    expect((await readdir(dirname(destination))).filter((name) => name.startsWith(".ctr-"))).toEqual([]);

    await expect(atomicWriteFileNoReplace(destination, "second\n")).rejects.toMatchObject({
      name: "SecureIoError",
      code: "ALREADY_EXISTS",
    });
    expect(await readFile(destination, "utf8")).toBe("first\n");
  });

  test("allows exactly one concurrent writer and never replaces the winner", async () => {
    const root = await privateTemporaryRoot();
    const output = await ensurePrivateDirectory(join(root, "output"));
    const destination = join(output, "race.txt");
    const payloads = Array.from({ length: 12 }, (_, index) => `payload-${index}`);
    const results = await Promise.allSettled(payloads.map((payload) => (
      atomicWriteFileNoReplace(destination, payload)
    )));

    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    const failures = results.filter((result) => result.status === "rejected");
    expect(failures).toHaveLength(payloads.length - 1);
    expect(failures.every((result) => result.reason instanceof SecureIoError && result.reason.code === "ALREADY_EXISTS")).toBe(true);
    expect(payloads).toContain(await readFile(destination, "utf8"));
    expect((await readdir(output)).filter((name) => name.startsWith(".ctr-"))).toEqual([]);
  });

  test("refuses a destination symlink without touching its target", async () => {
    const root = await privateTemporaryRoot();
    const output = await ensurePrivateDirectory(join(root, "output"));
    const outside = join(root, "outside.txt");
    await writeFile(outside, "outside", { mode: 0o600 });
    const destination = join(output, "artifact.txt");
    await symlink(outside, destination, "file");

    await expect(atomicWriteFileNoReplace(destination, "replacement")).rejects.toMatchObject({
      code: "SYMLINK_REJECTED",
    });
    expect(await readFile(outside, "utf8")).toBe("outside");
  });

  test("writes deterministic sorted JSON once and rejects insecure existing directories", async () => {
    const root = await privateTemporaryRoot();
    const output = await ensurePrivateDirectory(join(root, "output"));
    const destination = join(output, "artifact.json");
    await atomicWriteJsonNoReplace(destination, { z: 1, a: { d: 4, c: 3 } });
    expect(await readFile(destination, "utf8")).toBe('{\n  "a": {\n    "c": 3,\n    "d": 4\n  },\n  "z": 1\n}\n');

    const insecure = join(root, "insecure");
    await mkdir(insecure, { mode: 0o755 });
    await chmod(insecure, 0o755);
    await expect(ensurePrivateDirectory(insecure)).rejects.toMatchObject({
      code: "INSECURE_PERMISSIONS",
      details: expect.objectContaining({ mode: 0o755 }),
    });
  });

  test("allocates timestamped run directories without overwriting collisions", async () => {
    const root = await privateTemporaryRoot();
    const output = join(root, "runs");
    const now = new Date("2026-08-21T12:34:56.789Z");
    const first = await createRunDirectory(output, "Acme Cloud", "平台工程师", { now });
    const second = await createRunDirectory(output, "Acme Cloud", "平台工程师", { now });

    expect(basename(first)).toMatch(/^acme-cloud--role-[0-9a-f]{10}--20260821T123456789000Z$/);
    expect(basename(second)).toBe(`${basename(first)}-001`);
    expect(Number((await stat(first, { bigint: true })).mode) & 0o777).toBe(0o700);
    expect(Number((await stat(second, { bigint: true })).mode) & 0o777).toBe(0o700);
  });
});

describe("exact-byte source identity", () => {
  test("hashes exact bytes and revalidates UTF-8 line spans and exact quotes", async () => {
    expect(sha256Utf8("abc")).toBe("sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    const bytes = Buffer.from("# 标题\n\n- Led API\n", "utf8");
    const quote = "- Led API";
    const startByte = bytes.indexOf(Buffer.from(quote, "utf8"));
    const span = sourceSpanFromBytes(bytes, startByte, startByte + Buffer.byteLength(quote));

    expect(span).toEqual({ start_line: 3, end_line: 3, start_byte: startByte, end_byte: startByte + 9 });
    expect(revalidateSourceSpan(bytes, span)).toBe(quote);
    expect(revalidateExactQuote(bytes, span, quote)).toBe(quote);
    expect(() => revalidateExactQuote(bytes, span, "Led API")).toThrow(SourceIdentityError);
    expect(() => revalidateSourceSpan(bytes, { ...span, start_line: 2 })).toThrow(SourceIdentityError);

    const multiByteStart = bytes.indexOf(Buffer.from("标", "utf8"));
    expect(() => sourceSpanFromBytes(bytes, multiByteStart + 1, multiByteStart + 3)).toThrow(SourceIdentityError);
  });

  test("securely proves source identity and exact quote without mutating the source", async () => {
    const root = await privateTemporaryRoot();
    const source = join(root, "source");
    await mkdir(join(source, "notes"), { recursive: true, mode: 0o700 });
    const sourcePath = join(source, "notes", "evidence.md");
    const text = "# F1 P0\n\n- Personally built the synthetic queue.\n";
    await writeFile(sourcePath, text, { mode: 0o400 });
    await chmod(sourcePath, 0o400);
    const before = await stat(sourcePath, { bigint: true });

    const snapshot = await readSourceSnapshot(source, "notes/evidence.md");
    const identity = await captureSourceIdentity(source, "notes/evidence.md");
    expect(identity).toEqual({ path: "notes/evidence.md", source_hash: snapshot.source_hash });
    expect(await revalidateSourceIdentity(source, identity)).toEqual(identity);
    const firstCopy = snapshot.copyBytes();
    firstCopy[0] = 0x78;
    expect(new TextDecoder().decode(snapshot.copyBytes())).toBe(text);
    expect(snapshot.source_hash).toBe(identity.source_hash);
    expect(snapshot.byte_length).toBe(Buffer.byteLength(text));
    const quote = "- Personally built the synthetic queue.";
    const quoteBytes = Buffer.from(quote, "utf8");
    const startByte = Buffer.from(text, "utf8").indexOf(quoteBytes);
    const span = sourceSpanFromBytes(snapshot.copyBytes(), startByte, startByte + quoteBytes.byteLength);
    expect(await revalidateSourceReference(source, {
      ...identity,
      span,
      exact_quote: quote,
    })).toEqual(identity);

    const after = await stat(sourcePath, { bigint: true });
    expect(after.mode).toBe(before.mode);
    expect(after.size).toBe(before.size);
    expect(after.mtimeNs).toBe(before.mtimeNs);
    expect(await readFile(sourcePath, "utf8")).toBe(text);

    await chmod(sourcePath, 0o600);
    await writeFile(sourcePath, `${text}\nchanged\n`);
    await expect(revalidateSourceIdentity(source, identity)).rejects.toMatchObject({
      name: "SourceIdentityError",
      code: "SOURCE_CHANGED",
    });
  });
});
