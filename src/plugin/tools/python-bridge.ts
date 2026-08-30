import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonObject | readonly JsonValue[];
export interface JsonObject {
  readonly [key: string]: JsonValue;
}

export const DEFAULT_PLUGIN_ROOT = fileURLToPath(new URL("../../../", import.meta.url));
export const DEFAULT_KERNEL_TIMEOUT_MS = 120_000;
const MAX_KERNEL_TIMEOUT_MS = 10 * 60_000;
const MAX_INPUT_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 16 * 1024 * 1024;
const TERMINATION_GRACE_MS = 400;

export type KernelOperation =
  | "discover-source-structure"
  | "validate-source-map"
  | "validate-role-input"
  | "validate-evidence-input"
  | "generate-from-ir"
  | "write-growth-roadmap"
  | "render"
  | "inspect-pdf";

interface KernelRequestBase {
  readonly operation: KernelOperation;
  readonly input?: JsonObject;
}

export type KernelRequest =
  | (KernelRequestBase & {
      readonly operation: "discover-source-structure";
      readonly sourceRoot: string;
    })
  | (KernelRequestBase & {
      readonly operation:
        | "validate-source-map"
        | "validate-role-input"
        | "validate-evidence-input";
      readonly sourceRoot: string;
      readonly input: JsonObject;
    })
  | (KernelRequestBase & {
      readonly operation: "generate-from-ir";
      readonly input: JsonObject;
      readonly sourceRoot?: string;
      readonly outputRoot?: string;
      readonly includeExtendedProfile?: boolean;
    })
  | (KernelRequestBase & {
      readonly operation: "write-growth-roadmap";
      readonly sourceRoot: string;
      readonly handoffPath: string;
      readonly planPath: string;
      readonly outputRoot: string;
    })
  | (KernelRequestBase & {
      readonly operation: "render";
      readonly documentPath: string;
      readonly outputPath?: string;
    })
  | (KernelRequestBase & {
      readonly operation: "inspect-pdf";
      readonly pdfPath: string;
      readonly documentPath: string;
      readonly maxPages?: number;
    });

export type KernelBridgeErrorCode =
  | "CANCELLED"
  | "TIMEOUT"
  | "INVALID_INPUT"
  | "TEMP_IO_FAILED"
  | "TEMP_CLEANUP_FAILED"
  | "SPAWN_FAILED"
  | "OUTPUT_LIMIT"
  | "OUTPUT_READ_FAILED"
  | "KERNEL_EXIT"
  | "MALFORMED_ERROR_JSON"
  | "MALFORMED_RESULT_JSON"
  | "UNEXPECTED_STDERR";

export interface StructuredKernelError {
  readonly code: KernelBridgeErrorCode;
  readonly message: string;
  readonly operation: KernelOperation;
  readonly retryable: boolean;
  readonly exitCode?: number;
  readonly kernelType?: string;
}

export class KernelBridgeError extends Error {
  readonly code: KernelBridgeErrorCode;
  readonly operation: KernelOperation;
  readonly retryable: boolean;
  readonly exitCode?: number;
  readonly kernelType?: string;

  constructor(error: StructuredKernelError, options?: ErrorOptions) {
    super(error.message, options);
    this.name = "KernelBridgeError";
    this.code = error.code;
    this.operation = error.operation;
    this.retryable = error.retryable;
    if (error.exitCode !== undefined) this.exitCode = error.exitCode;
    if (error.kernelType !== undefined) this.kernelType = error.kernelType;
  }

  structured(): StructuredKernelError {
    return Object.freeze({
      code: this.code,
      message: this.message,
      operation: this.operation,
      retryable: this.retryable,
      ...(this.exitCode === undefined ? {} : { exitCode: this.exitCode }),
      ...(this.kernelType === undefined ? {} : { kernelType: this.kernelType }),
    });
  }
}

export interface KernelProcess {
  readonly pid: number;
  readonly stdout: ReadableStream<Uint8Array>;
  readonly stderr: ReadableStream<Uint8Array>;
  readonly exited: Promise<number>;
  readonly exitCode: number | null;
  kill(signal?: NodeJS.Signals | number): void;
}

export interface KernelSpawnOptions {
  readonly cwd: string;
  readonly env: Readonly<Record<string, string>>;
  readonly stdin: Blob;
  readonly detached: true;
  readonly maxBuffer: number;
}

export type KernelSpawner = (
  command: readonly string[],
  options: KernelSpawnOptions,
) => KernelProcess;

export type ProcessTreeTerminator = (process: KernelProcess) => Promise<void>;

export interface PythonKernelBridgeOptions {
  readonly pluginRoot?: string;
  readonly tempRoot?: string;
  readonly defaultTimeoutMs?: number;
  readonly spawn?: KernelSpawner;
  readonly terminateProcessTree?: ProcessTreeTerminator;
}

export interface KernelRunOptions {
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}

function assertSafePath(value: string, label: string): string {
  if (!value || value.includes("\0") || value.includes("\n") || value.includes("\r")) {
    throw new Error(`${label} must be a non-empty filesystem path`);
  }
  return value;
}

/** Build the only argv shapes the bridge permits. JSON payloads never enter it. */
export function buildPythonKernelInvocation(pluginRoot: string, request: KernelRequest): readonly string[] {
  const root = resolve(assertSafePath(pluginRoot, "Plugin root"));
  const command = [
    "uv",
    "run",
    "--project",
    root,
    "--offline",
    "--frozen",
    "china-targeted-resume",
    request.operation,
  ];
  switch (request.operation) {
    case "discover-source-structure":
    case "validate-source-map":
    case "validate-role-input":
    case "validate-evidence-input":
      command.push("--source", assertSafePath(request.sourceRoot, "Source root"));
      break;
    case "generate-from-ir":
      if (request.sourceRoot !== undefined) command.push("--source", assertSafePath(request.sourceRoot, "Source root"));
      if (request.outputRoot !== undefined) command.push("--output-root", assertSafePath(request.outputRoot, "Output root"));
      if (request.includeExtendedProfile === true) command.push("--include-extended-profile");
      break;
    case "write-growth-roadmap":
      command.push("--source", assertSafePath(request.sourceRoot, "Source root"));
      command.push("--handoff", assertSafePath(request.handoffPath, "Roadmap handoff"));
      command.push("--plan", assertSafePath(request.planPath, "Growth roadmap plan"));
      command.push("--output", assertSafePath(request.outputRoot, "Output root"));
      break;
    case "render":
      command.push("--document", assertSafePath(request.documentPath, "Resume document"));
      if (request.outputPath !== undefined) command.push("--output", assertSafePath(request.outputPath, "PDF output"));
      break;
    case "inspect-pdf":
      command.push("--pdf", assertSafePath(request.pdfPath, "PDF input"));
      command.push("--document", assertSafePath(request.documentPath, "Resume document"));
      if (request.maxPages !== undefined) command.push("--max-pages", String(request.maxPages));
      break;
    default: {
      const exhaustive: never = request;
      throw new Error(`Unsupported kernel request: ${String(exhaustive)}`);
    }
  }
  return Object.freeze(command);
}

function spawnWithBun(command: readonly string[], options: KernelSpawnOptions): KernelProcess {
  return Bun.spawn({
    cmd: [...command],
    cwd: options.cwd,
    env: { ...options.env },
    stdin: options.stdin,
    stdout: "pipe",
    stderr: "pipe",
    detached: options.detached,
    maxBuffer: options.maxBuffer,
  }) as KernelProcess;
}

function delay(milliseconds: number): Promise<void> {
  const { promise, resolve: resolveDelay } = Promise.withResolvers<void>();
  setTimeout(resolveDelay, milliseconds);
  return promise;
}

export async function terminateKernelProcessTree(processHandle: KernelProcess): Promise<void> {
  const signalGroup = (signal: NodeJS.Signals): void => {
    if (process.platform !== "win32" && processHandle.pid > 0) {
      try {
        process.kill(-processHandle.pid, signal);
        return;
      } catch {
        // Fall through when a platform/runtime cannot signal the process group.
      }
    }
    try {
      processHandle.kill(signal);
    } catch {
      // The process may have exited between the state check and signal.
    }
  };

  signalGroup("SIGTERM");
  const terminated = await Promise.race([
    processHandle.exited.then(() => true, () => true),
    delay(TERMINATION_GRACE_MS).then(() => false),
  ]);
  if (!terminated) {
    signalGroup("SIGKILL");
    await Promise.race([
      processHandle.exited.then(() => undefined, () => undefined),
      delay(TERMINATION_GRACE_MS),
    ]);
  }
}

interface StreamDrain {
  readonly result: Promise<string>;
  cancel(): Promise<void>;
}

function drainUtf8(stream: ReadableStream<Uint8Array>, limit: number): StreamDrain {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  const result = (async (): Promise<string> => {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > limit) {
        await reader.cancel("kernel output limit exceeded").catch(() => undefined);
        throw new RangeError("kernel output limit exceeded");
      }
      chunks.push(next.value);
    }
    const combined = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      combined.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return new TextDecoder("utf-8", { fatal: true }).decode(combined);
  })();
  return {
    result,
    async cancel(): Promise<void> {
      await reader.cancel("kernel bridge cancelled").catch(() => undefined);
    },
  };
}

function privateKernelEnvironment(workspace: string): Record<string, string> {
  const allowed = [
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PLAYWRIGHT_BROWSERS_PATH",
    "SYSTEMROOT",
    "UV_CACHE_DIR",
    "XDG_CACHE_HOME",
  ] as const;
  const environment: Record<string, string> = {};
  for (const key of allowed) {
    const value = process.env[key];
    if (value !== undefined) environment[key] = value;
  }
  environment.TMPDIR = workspace;
  environment.TMP = workspace;
  environment.TEMP = workspace;
  environment.PYTHONUTF8 = "1";
  environment.PYTHONUNBUFFERED = "1";
  environment.UV_OFFLINE = "1";
  environment.NO_COLOR = "1";
  environment.NO_PROXY = "*";
  environment.HTTP_PROXY = "";
  environment.HTTPS_PROXY = "";
  environment.ALL_PROXY = "";
  return environment;
}

function parseJsonObject(value: string): JsonObject | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return undefined;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return undefined;
  return parsed as JsonObject;
}

function safeKernelMessage(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const singleLine = value.replace(/[\r\n\t]+/g, " ").trim().slice(0, 512);
  if (!singleLine) return undefined;
  return singleLine
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[redacted-contact]")
    .replace(/\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{10,}\b/g, "[redacted-credential]")
    .replace(/(?:^|\s)\/(?:[^\s/]+\/)+[^\s]*/g, " [private-path]");
}

function normalizeTimeout(timeoutMs: number | undefined, fallback: number): number {
  const timeout = timeoutMs ?? fallback;
  if (!Number.isSafeInteger(timeout) || timeout <= 0 || timeout > MAX_KERNEL_TIMEOUT_MS) {
    throw new Error(`Kernel timeout must be an integer between 1 and ${MAX_KERNEL_TIMEOUT_MS} milliseconds`);
  }
  return timeout;
}

export class PythonKernelBridge {
  readonly #pluginRoot: string;
  readonly #tempRoot: string;
  readonly #defaultTimeoutMs: number;
  readonly #spawn: KernelSpawner;
  readonly #terminateProcessTree: ProcessTreeTerminator;

  constructor(options: PythonKernelBridgeOptions = {}) {
    this.#pluginRoot = resolve(options.pluginRoot ?? DEFAULT_PLUGIN_ROOT);
    this.#tempRoot = resolve(options.tempRoot ?? tmpdir());
    this.#defaultTimeoutMs = normalizeTimeout(options.defaultTimeoutMs, DEFAULT_KERNEL_TIMEOUT_MS);
    this.#spawn = options.spawn ?? spawnWithBun;
    this.#terminateProcessTree = options.terminateProcessTree ?? terminateKernelProcessTree;
  }

  async run(request: KernelRequest, options: KernelRunOptions = {}): Promise<JsonObject> {
    if (options.signal?.aborted) {
      throw new KernelBridgeError({
        code: "CANCELLED",
        message: "Python kernel call was cancelled before launch",
        operation: request.operation,
        retryable: true,
      });
    }

    let serialized: string;
    try {
      const input = request.input ?? {};
      serialized = `${JSON.stringify(input)}\n`;
      if (new TextEncoder().encode(serialized).byteLength > MAX_INPUT_BYTES) {
        throw new RangeError("input exceeds limit");
      }
    } catch (cause) {
      throw new KernelBridgeError(
        {
          code: "INVALID_INPUT",
          message: "Kernel input must be one JSON object no larger than 8 MiB",
          operation: request.operation,
          retryable: false,
        },
        { cause },
      );
    }

    let workspace: string | undefined;
    try {
      workspace = await mkdtemp(join(this.#tempRoot, "china-targeted-resume-"));
      await chmod(workspace, 0o700);
      const inputPath = join(workspace, "request.json");
      await writeFile(inputPath, serialized, { encoding: "utf8", flag: "wx", mode: 0o600 });
      await chmod(inputPath, 0o600);
      return await this.#runPrepared(request, inputPath, workspace, options);
    } catch (cause) {
      if (cause instanceof KernelBridgeError) throw cause;
      throw new KernelBridgeError(
        {
          code: "TEMP_IO_FAILED",
          message: "Could not create the private temporary kernel workspace",
          operation: request.operation,
          retryable: true,
        },
        { cause },
      );
    } finally {
      if (workspace !== undefined) {
        try {
          await rm(workspace, { recursive: true, force: true });
        } catch (cause) {
          throw new KernelBridgeError(
            {
              code: "TEMP_CLEANUP_FAILED",
              message: "Private kernel workspace cleanup failed; remove the Plugin temporary directory before retrying",
              operation: request.operation,
              retryable: false,
            },
            { cause },
          );
        }
      }
    }
  }

  async #runPrepared(
    request: KernelRequest,
    inputPath: string,
    workspace: string,
    options: KernelRunOptions,
  ): Promise<JsonObject> {
    const command = buildPythonKernelInvocation(this.#pluginRoot, request);
    let processHandle: KernelProcess;
    try {
      processHandle = this.#spawn(command, {
        cwd: this.#pluginRoot,
        env: privateKernelEnvironment(workspace),
        stdin: Bun.file(inputPath),
        detached: true,
        maxBuffer: MAX_OUTPUT_BYTES,
      });
    } catch (cause) {
      throw new KernelBridgeError(
        {
          code: "SPAWN_FAILED",
          message: "Could not start the bundled Python kernel with uv; install uv and sync this Plugin project offline first",
          operation: request.operation,
          retryable: true,
        },
        { cause },
      );
    }

    const stdout = drainUtf8(processHandle.stdout, MAX_OUTPUT_BYTES);
    const stderr = drainUtf8(processHandle.stderr, MAX_OUTPUT_BYTES);
    const timeoutMs = normalizeTimeout(options.timeoutMs, this.#defaultTimeoutMs);
    const { promise: interrupted, resolve: resolveInterrupt } = Promise.withResolvers<"cancelled" | "timeout">();
    const timeout = setTimeout(() => resolveInterrupt("timeout"), timeoutMs);
    const abortHandler = () => resolveInterrupt("cancelled");
    options.signal?.addEventListener("abort", abortHandler, { once: true });
    if (options.signal?.aborted) resolveInterrupt("cancelled");
    const completed = Promise.all([processHandle.exited, stdout.result, stderr.result]).then(
      ([exitCode, standardOutput, standardError]) => ({
        kind: "completed" as const,
        exitCode,
        standardOutput,
        standardError,
      }),
      (error: unknown) => ({ kind: "stream-error" as const, error }),
    );

    try {
      const outcome = await Promise.race([
        completed,
        interrupted.then((reason) => ({ kind: "interrupted" as const, reason })),
      ]);
      if (outcome.kind === "interrupted") {
        await this.#terminateProcessTree(processHandle);
        await Promise.race([
          Promise.allSettled([stdout.cancel(), stderr.cancel()]).then(() => undefined),
          delay(TERMINATION_GRACE_MS),
        ]);
        throw new KernelBridgeError({
          code: outcome.reason === "timeout" ? "TIMEOUT" : "CANCELLED",
          message:
            outcome.reason === "timeout"
              ? `Python kernel exceeded its ${timeoutMs} ms timeout and was terminated`
              : "Python kernel call was cancelled and its process tree was terminated",
          operation: request.operation,
          retryable: true,
        });
      }
      if (outcome.kind === "stream-error") {
        await this.#terminateProcessTree(processHandle);
        await Promise.race([
          Promise.allSettled([stdout.cancel(), stderr.cancel()]).then(() => undefined),
          delay(TERMINATION_GRACE_MS),
        ]);
        const outputLimit = outcome.error instanceof RangeError;
        throw new KernelBridgeError(
          {
            code: outputLimit ? "OUTPUT_LIMIT" : "OUTPUT_READ_FAILED",
            message: outputLimit
              ? "Python kernel output exceeded the 16 MiB safety limit"
              : "Python kernel output could not be read as UTF-8",
            operation: request.operation,
            retryable: false,
          },
          { cause: outcome.error },
        );
      }
      return this.#parseResult(request.operation, outcome.exitCode, outcome.standardOutput, outcome.standardError);
    } finally {
      clearTimeout(timeout);
      options.signal?.removeEventListener("abort", abortHandler);
    }
  }

  #parseResult(operation: KernelOperation, exitCode: number, stdout: string, stderr: string): JsonObject {
    if (exitCode !== 0) {
      const errorPayload = parseJsonObject(stderr.trim());
      if (!errorPayload) {
        throw new KernelBridgeError({
          code: "MALFORMED_ERROR_JSON",
          message: `Python kernel exited with code ${exitCode} but did not return its required JSON error object`,
          operation,
          retryable: false,
          exitCode,
        });
      }
      const kernelMessage = safeKernelMessage(errorPayload.error);
      const kernelType = typeof errorPayload.type === "string" && /^[A-Za-z][A-Za-z0-9_]{0,127}$/.test(errorPayload.type)
        ? errorPayload.type
        : undefined;
      throw new KernelBridgeError({
        code: "KERNEL_EXIT",
        message: kernelMessage ?? `Python kernel rejected ${operation}`,
        operation,
        retryable: false,
        exitCode,
        ...(kernelType === undefined ? {} : { kernelType }),
      });
    }
    if (stderr.trim().length > 0) {
      throw new KernelBridgeError({
        code: "UNEXPECTED_STDERR",
        message: "Python kernel returned stderr on a successful exit; inspect the local runtime without copying private stderr into the session",
        operation,
        retryable: false,
      });
    }
    const result = parseJsonObject(stdout.trim());
    if (!result) {
      throw new KernelBridgeError({
        code: "MALFORMED_RESULT_JSON",
        message: "Python kernel returned malformed JSON; verify that the Plugin and bundled Python project versions match",
        operation,
        retryable: false,
      });
    }
    return Object.freeze(result);
  }
}
