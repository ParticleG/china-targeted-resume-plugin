import { afterEach, describe, expect, test, vi } from "bun:test";
import { chmod, mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  buildPythonKernelInvocation,
  KernelBridgeError,
  PythonKernelBridge,
  type KernelProcess,
  type KernelSpawnOptions,
  type KernelSpawner,
} from "../../src/plugin/tools/python-bridge.ts";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  vi.useRealTimers();
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

interface CapturedSpawn {
  command?: readonly string[];
  options?: KernelSpawnOptions;
  input?: string;
  inputReady?: Promise<string>;
}

function textStream(text: string): ReadableStream<Uint8Array> {
  return new Blob([text]).stream();
}

function settledProcess(exitCode: number, stdout: string, stderr = ""): KernelProcess {
  return {
    pid: 456_789,
    stdout: textStream(stdout),
    stderr: textStream(stderr),
    exited: Promise.resolve(exitCode),
    exitCode,
    kill() {},
  };
}

async function privateTempRoot(): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), "ctr-bridge-test-"));
  temporaryDirectories.push(path);
  await chmod(path, 0o700);
  return path;
}

function capturingSpawner(
  captured: CapturedSpawn,
  processFactory: () => KernelProcess,
): KernelSpawner {
  return (command, options) => {
    captured.command = command;
    captured.options = options;
    captured.inputReady = options.stdin.text().then((input) => {
      captured.input = input;
      return input;
    });
    return processFactory();
  };
}

describe("Python kernel invocation", () => {
  test("uses a static uv argument array rooted at the Plugin project", () => {
    expect(buildPythonKernelInvocation("/opt/china-targeted-resume-plugin", {
      operation: "validate-role-input",
      sourceRoot: "/private/career-source",
      input: { sentinel: "never-in-argv" },
    })).toEqual([
      "uv",
      "run",
      "--project",
      "/opt/china-targeted-resume-plugin",
      "--offline",
      "--frozen",
      "china-targeted-resume",
      "validate-role-input",
      "--source",
      "/private/career-source",
    ]);
  });

  test("binds PDF inspection to the authoritative ResumeDocument argument", () => {
    expect(buildPythonKernelInvocation("/plugin", {
      operation: "inspect-pdf",
      pdfPath: "/run/recruiter.pdf",
      documentPath: "/run/recruiter.resume-document.json",
      maxPages: 1,
      input: {},
    })).toEqual([
      "uv",
      "run",
      "--project",
      "/plugin",
      "--offline",
      "--frozen",
      "china-targeted-resume",
      "inspect-pdf",
      "--pdf",
      "/run/recruiter.pdf",
      "--document",
      "/run/recruiter.resume-document.json",
      "--max-pages",
      "1",
    ]);
  });

  test("keeps private JSON out of argv and drains a strict JSON result", async () => {
    const tempRoot = await privateTempRoot();
    const captured: CapturedSpawn = {};
    const bridge = new PythonKernelBridge({
      pluginRoot: "/opt/china-targeted-resume-plugin",
      tempRoot,
      spawn: capturingSpawner(captured, () => settledProcess(0, '{"operation":"validate-role-input","valid":true}\n')),
    });
    const privatePayload = "PRIVATE-CANDIDATE-SENTINEL";

    const result = await bridge.run({
      operation: "validate-role-input",
      sourceRoot: "/private/career-source",
      input: { privatePayload },
    });
    await captured.inputReady;

    expect(result).toEqual({ operation: "validate-role-input", valid: true });
    expect(captured.command).not.toContain(privatePayload);
    expect(captured.command?.join(" ")).not.toContain(privatePayload);
    expect(JSON.parse(captured.input!)).toEqual({ privatePayload });
    expect(captured.options?.env.UV_OFFLINE).toBe("1");
    expect(captured.options?.env).not.toHaveProperty("OPENAI_API_KEY");
    expect(captured.options?.detached).toBe(true);
    await expect(Bun.file(captured.options!.env["TMPDIR"]!).exists()).resolves.toBe(false);
  });

  test("creates private temporary input and removes it after completion", async () => {
    const tempRoot = await privateTempRoot();
    let workspaceMode: number | undefined;
    let inputMode: number | undefined;
    let inputPath: string | undefined;
    let metadataReady: Promise<void> | undefined;
    const bridge = new PythonKernelBridge({
      pluginRoot: "/plugin",
      tempRoot,
      spawn(command, options) {
        void command;
        const stdin = options.stdin as Blob & { name?: string };
        const observedInputPath = stdin.name;
        inputPath = observedInputPath;
        if (observedInputPath) {
          metadataReady = Promise.all([
            stat(options.env["TMPDIR"]!),
            stat(observedInputPath),
          ]).then(([workspace, input]) => {
            workspaceMode = Number(workspace.mode) & 0o777;
            inputMode = Number(input.mode) & 0o777;
          });
        }
        return settledProcess(0, '{"operation":"discover-source-structure"}');
      },
    });

    await bridge.run({ operation: "discover-source-structure", sourceRoot: "/source", input: {} });
    await metadataReady;

    expect(workspaceMode).toBe(0o700);
    expect(inputMode).toBe(0o600);
    expect(inputPath).toBeDefined();
    await expect(Bun.file(inputPath!).exists()).resolves.toBe(false);
  });
});

describe("Python kernel JSON and process failures", () => {
  test("maps malformed success JSON to an actionable structured error", async () => {
    const bridge = new PythonKernelBridge({
      pluginRoot: "/plugin",
      tempRoot: await privateTempRoot(),
      spawn: () => settledProcess(0, "not-json"),
    });

    await expect(bridge.run({ operation: "discover-source-structure", sourceRoot: "/source" })).rejects.toMatchObject({
      name: "KernelBridgeError",
      code: "MALFORMED_RESULT_JSON",
      operation: "discover-source-structure",
      retryable: false,
    });
  });

  test("maps nonzero JSON stderr without retaining private stderr", async () => {
    const privatePath = "/home/candidate/private/evidence.md";
    const bridge = new PythonKernelBridge({
      pluginRoot: "/plugin",
      tempRoot: await privateTempRoot(),
      spawn: () => settledProcess(2, "", JSON.stringify({
        error: `Validation failed at ${privatePath} for person@example.invalid`,
        type: "IRValidationError",
      })),
    });

    let failure: unknown;
    try {
      await bridge.run({ operation: "validate-source-map", sourceRoot: "/source", input: {} });
    } catch (error) {
      failure = error;
    }

    expect(failure).toBeInstanceOf(KernelBridgeError);
    expect(failure).toMatchObject({
      code: "KERNEL_EXIT",
      exitCode: 2,
      kernelType: "IRValidationError",
    });
    expect((failure as Error).message).not.toContain(privatePath);
    expect((failure as Error).message).not.toContain("person@example.invalid");
  });

  test("rejects malformed nonzero stderr as a JSON contract violation", async () => {
    const bridge = new PythonKernelBridge({
      pluginRoot: "/plugin",
      tempRoot: await privateTempRoot(),
      spawn: () => settledProcess(9, "", "python traceback with private values"),
    });

    await expect(bridge.run({ operation: "discover-source-structure", sourceRoot: "/source" })).rejects.toMatchObject({
      code: "MALFORMED_ERROR_JSON",
      exitCode: 9,
    });
  });

  test("propagates caller cancellation and terminates the child process tree", async () => {
    const exited = Promise.withResolvers<number>();
    const controller = new AbortController();
    let terminations = 0;
    const bridge = new PythonKernelBridge({
      pluginRoot: "/plugin",
      tempRoot: await privateTempRoot(),
      spawn: () => {
        queueMicrotask(() => controller.abort());
        return {
          pid: 456_790,
          stdout: textStream(""),
          stderr: textStream(""),
          exited: exited.promise,
          exitCode: null,
          kill() {},
        };
      },
      async terminateProcessTree() {
        terminations += 1;
        exited.resolve(143);
      },
    });

    await expect(bridge.run(
      { operation: "discover-source-structure", sourceRoot: "/source" },
      { signal: controller.signal },
    )).rejects.toMatchObject({ code: "CANCELLED", retryable: true });
    expect(terminations).toBe(1);
  });

  test("enforces timeout without waiting indefinitely for a stuck child exit promise", async () => {
    vi.useFakeTimers();
    const { promise: neverExits } = Promise.withResolvers<number>();
    const spawned = Promise.withResolvers<void>();
    let terminations = 0;
    const bridge = new PythonKernelBridge({
      pluginRoot: "/plugin",
      tempRoot: await privateTempRoot(),
      spawn: () => {
        spawned.resolve();
        return {
          pid: 456_791,
          stdout: textStream(""),
          stderr: textStream(""),
          exited: neverExits,
          exitCode: null,
          kill() {},
        };
      },
      async terminateProcessTree() {
        terminations += 1;
      },
    });

    const pending = bridge.run(
      { operation: "discover-source-structure", sourceRoot: "/source" },
      { timeoutMs: 5 },
    );
    await spawned.promise;
    vi.advanceTimersByTime(5);
    await expect(pending).rejects.toMatchObject({ code: "TIMEOUT", retryable: true });
    expect(terminations).toBe(1);
  });
});
