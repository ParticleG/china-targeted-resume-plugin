import { describe, expect, test } from "bun:test";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { RESUME_TOOL_NAMES } from "../../src/plugin/runtime.ts";
import { RESUME_COMMAND_NAMES } from "../../src/plugin/commands/index.ts";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));

async function readProjectFile(path: string): Promise<string> {
  return readFile(join(ROOT, path), "utf8");
}

function toolBackendRows(markdown: string): Map<string, string> {
  const heading = "## Per-tool backend matrix";
  const start = markdown.indexOf(heading);
  expect(start).toBeGreaterThanOrEqual(0);
  const section = markdown.slice(start + heading.length).split("\n## ", 1)[0] ?? "";
  const rows = new Map<string, string>();

  for (const line of section.split("\n")) {
    if (!line.startsWith("| `resume_")) continue;
    const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
    expect(cells).toHaveLength(3);
    const tool = cells[0]?.replaceAll("`", "");
    const backend = cells[1];
    expect(tool).toBeTruthy();
    expect(backend).toBeTruthy();
    rows.set(tool!, backend!);
  }

  return rows;
}

describe("documented Phase 3 product boundary", () => {
  test("the per-tool matrix covers every registered tool once and names the configured language", async () => {
    const boundary = await readProjectFile("docs/final-product-boundary.md");
    const rows = toolBackendRows(boundary);

    expect([...rows.keys()]).toEqual([...RESUME_TOOL_NAMES]);
    expect(rows.get("resume_read_source_slice")).toBe("TypeScript");
    expect(rows.get("resume_lock_approved_claims")).toBe("TypeScript");

    for (const tool of [
      "resume_discover_structure",
      "resume_validate_source_map",
      "resume_validate_role_ir",
      "resume_validate_evidence_ir",
      "resume_compose_variants",
      "resume_render_variants",
      "resume_inspect_variants",
    ]) {
      expect(rows.get(tool)).toContain("Python");
    }
  });

  test("the final boundary is Option A with explicit runtimes and no silent backend retry", async () => {
    const boundary = await readProjectFile("docs/final-product-boundary.md");

    expect(boundary).toContain("Option A: Plugin-first hybrid");
    expect(boundary).toContain("OMP `>=17.3.7`");
    expect(boundary).toContain("Bun `>=1.3.0`");
    expect(boundary).toContain("Python `>=3.14`");
    expect(boundary).toContain("ParticleG/china-targeted-resume-plugin");
    expect(boundary).toContain("gate is observed");
    expect(boundary).toContain("There is no backend preference flag");
    expect(boundary).not.toMatch(/fall(?:s|ing)? back to (?:the )?(?:Python|TypeScript)/i);
  });

  test("parity documentation preserves evidence states and exact normalization limits", async () => {
    const parity = await readProjectFile("docs/parity-matrix.md");

    for (const label of [
      "Source-verified",
      "Mechanically transformed",
      "Independently reviewed",
      "User-confirmed",
    ]) {
      expect(parity).toContain(label);
    }
    expect(parity).toContain("## Exact normalization policy");
    expect(parity).toContain("Object member order");
    expect(parity).toContain("Array order is never normalized");
    expect(parity).toContain("Source hashes, source spans, stable IDs, claim text, policy values, review outcomes, provenance links, variant order, and artifact base names are never normalized");
    expect(parity).toContain("## Final verification matrix");
  });

  test("both READMEs describe the hybrid boundary and do not retain the all-Python Plugin claim", async () => {
    const english = await readProjectFile("README.md");
    const chinese = await readProjectFile("README.zh_CN.md");

    for (const readme of [english, chinese]) {
      expect(readme).toContain("Plugin-first hybrid");
      expect(readme).toContain("docs/parity-matrix.md");
      expect(readme).toContain("docs/final-product-boundary.md");
      expect(readme).toContain("17.3.7");
    }
    expect(english).not.toContain("typed tools invoke the deterministic Python kernel");
    expect(chinese).not.toContain("类型化工具调用确定性的 Python 内核");
  });

  test("both READMEs document every registered command and deterministic help", async () => {
    const english = await readProjectFile("README.md");
    const chinese = await readProjectFile("README.zh_CN.md");
    const boundary = await readProjectFile("docs/final-product-boundary.md");

    expect(RESUME_COMMAND_NAMES).toHaveLength(7);
    for (const command of RESUME_COMMAND_NAMES) {
      expect(english).toContain(`/${command}`);
      expect(chinese).toContain(`/${command}`);
    }
    for (const readme of [english, chinese]) {
      expect(readme).toContain("/resume-help [topic]");
      expect(readme).toContain("resume_validate_source_map");
      expect(readme).toContain("resume_lock_approved_claims");
      expect(readme).toContain("resume-variants.json");
    }
    expect(boundary).toContain("The seven slash commands");
    expect(boundary).toContain("model-free");
  });

  test("package metadata pins the parity validator, runtime floor, and installed documentation", async () => {
    const packageJson = JSON.parse(await readProjectFile("package.json")) as {
      readonly files: readonly string[];
      readonly dependencies: Readonly<Record<string, string>>;
      readonly devDependencies: Readonly<Record<string, string>>;
      readonly engines: Readonly<Record<string, string>>;
    };

    expect(packageJson.files).toContain("docs");
    expect(packageJson.files).toContain("schemas");
    expect(packageJson.files).toContain("src/kernel");
    expect(packageJson.dependencies.ajv).toBe("8.17.1");
    expect(packageJson.dependencies["ajv-formats"]).toBe("3.0.1");
    expect(packageJson.devDependencies["@oh-my-pi/pi-coding-agent"]).toBe("17.3.7");
    expect(packageJson.engines.bun).toBe(">=1.3.0");
  });

  test("the switched approval tool has no Python bridge alias or silent alternate path", async () => {
    const tools = await readProjectFile("src/plugin/tools/index.ts");
    const lockStart = tools.indexOf('name: "resume_lock_approved_claims"');
    const composeStart = tools.indexOf('name: "resume_compose_variants"', lockStart);
    expect(lockStart).toBeGreaterThanOrEqual(0);
    expect(composeStart).toBeGreaterThan(lockStart);
    const lockTool = tools.slice(lockStart, composeStart);

    expect(lockTool).toContain("revalidateApprovalSources");
    expect(lockTool).toContain("approveAndLockClaims");
    expect(lockTool).not.toContain("bridge.run");
    expect(lockTool).not.toContain('"approve-claims"');

    const pythonBridge = await readProjectFile("src/plugin/tools/python-bridge.ts");
    expect(pythonBridge).not.toContain('"approve-claims"');
  });

  test("the root schema directory remains the sole Draft 2020-12 authority", async () => {
    const schemaDirectory = join(ROOT, "schemas");
    const schemaNames = (await readdir(schemaDirectory))
      .filter((name) => name.endsWith(".schema.json"))
      .sort();

    expect(schemaNames.length).toBeGreaterThan(0);
    for (const schemaName of schemaNames) {
      const schema = JSON.parse(await readFile(join(schemaDirectory, schemaName), "utf8")) as Record<string, unknown>;
      expect(schema.$schema).toBe("https://json-schema.org/draft/2020-12/schema");
    }
  });
});
