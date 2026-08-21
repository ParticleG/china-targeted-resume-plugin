import { afterEach, describe, expect, test } from "bun:test";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  readVariantManifest,
  resolveVariantArtifacts,
} from "../../src/plugin/manifest.ts";

const temporaryDirectories: string[] = [];

interface RunFixture {
  readonly root: string;
  readonly runDirectory: string;
  readonly manifestPath: string;
  readonly documentPath: string;
  readonly pdfPath: string;
}

async function createRunFixture(): Promise<RunFixture> {
  const root = await mkdtemp(join(tmpdir(), "ctr-manifest-security-"));
  temporaryDirectories.push(root);
  await chmod(root, 0o700);
  const runDirectory = join(root, "run");
  await mkdir(runDirectory, { mode: 0o700 });
  await chmod(runDirectory, 0o700);
  const documentPath = join(runDirectory, "resume.document.json");
  const pdfPath = join(runDirectory, "resume.pdf");
  await writeFile(documentPath, "{}\n", { mode: 0o600 });
  await writeFile(pdfPath, "%PDF-synthetic\n", { mode: 0o600 });
  await chmod(documentPath, 0o600);
  await chmod(pdfPath, 0o600);
  const manifestPath = join(runDirectory, "resume-variants.json");
  await writeFile(manifestPath, JSON.stringify({
    schema_version: 1,
    variants: [{
      variant: "technical-two-page",
      target_pages: 2,
      actual_pages: 1,
      audit_success: true,
      pdf_success: true,
      artifacts: {
        document: "resume.document.json",
        pdf: "resume.pdf",
      },
    }],
  }), { mode: 0o600 });
  await chmod(manifestPath, 0o600);
  return { root, runDirectory, manifestPath, documentPath, pdfPath };
}

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
});

describe("variant manifest filesystem boundary", () => {
  test("reads a private manifest and resolves private regular artifacts", async () => {
    const fixture = await createRunFixture();
    const manifest = await readVariantManifest(fixture.manifestPath);
    expect(manifest.variants).toHaveLength(1);
    expect(await resolveVariantArtifacts(fixture.manifestPath, manifest, "document")).toEqual([{
      variant: "technical-two-page",
      path: fixture.documentPath,
    }]);
    expect(await readFile(fixture.documentPath, "utf8")).toBe("{}\n");
  });

  test("rejects a manifest symlink even when its target remains inside the run directory", async () => {
    const fixture = await createRunFixture();
    const realManifest = join(fixture.runDirectory, "manifest-real.json");
    const payload = await readFile(fixture.manifestPath);
    await rm(fixture.manifestPath);
    await writeFile(realManifest, payload, { mode: 0o600 });
    await chmod(realManifest, 0o600);
    await symlink(realManifest, fixture.manifestPath, "file");

    await expect(readVariantManifest(fixture.manifestPath)).rejects.toMatchObject({
      name: "ManifestContractError",
      code: "UNSAFE_MANIFEST",
    });
  });

  test("rejects an in-run artifact symlink instead of accepting its resolved target", async () => {
    const fixture = await createRunFixture();
    const realPdf = join(fixture.root, "outside-run.pdf");
    const payload = await readFile(fixture.pdfPath);
    await rm(fixture.pdfPath);
    await writeFile(realPdf, payload, { mode: 0o600 });
    await chmod(realPdf, 0o600);
    await symlink(realPdf, fixture.pdfPath, "file");
    const manifest = await readVariantManifest(fixture.manifestPath);

    await expect(resolveVariantArtifacts(fixture.manifestPath, manifest, "pdf")).rejects.toMatchObject({
      code: "UNSAFE_ARTIFACT",
    });
  });

  test("rejects permissive run-directory, manifest, and artifact modes", async () => {
    const fixture = await createRunFixture();
    await chmod(fixture.runDirectory, 0o755);
    await expect(readVariantManifest(fixture.manifestPath)).rejects.toMatchObject({
      code: "INSECURE_RUN_DIRECTORY",
    });

    await chmod(fixture.runDirectory, 0o700);
    await chmod(fixture.manifestPath, 0o644);
    await expect(readVariantManifest(fixture.manifestPath)).rejects.toMatchObject({
      code: "INSECURE_MANIFEST",
    });

    await chmod(fixture.manifestPath, 0o600);
    const manifest = await readVariantManifest(fixture.manifestPath);
    await chmod(fixture.documentPath, 0o644);
    await expect(resolveVariantArtifacts(fixture.manifestPath, manifest, "document")).rejects.toMatchObject({
      code: "INSECURE_ARTIFACT",
    });
  });

  test("rejects a symlinked run directory and a symlink in its parent chain", async () => {
    const fixture = await createRunFixture();
    const runAlias = join(fixture.root, "run-alias");
    await symlink(fixture.runDirectory, runAlias, "dir");
    await expect(readVariantManifest(join(runAlias, "resume-variants.json"))).rejects.toMatchObject({
      code: "INSECURE_RUN_DIRECTORY",
    });

    const realParent = join(fixture.root, "real-parent");
    await mkdir(realParent, { mode: 0o700 });
    const nestedRun = join(realParent, "nested-run");
    await mkdir(nestedRun, { mode: 0o700 });
    const nestedManifest = join(nestedRun, "resume-variants.json");
    await writeFile(nestedManifest, await readFile(fixture.manifestPath), { mode: 0o600 });
    await chmod(nestedManifest, 0o600);
    const parentAlias = join(fixture.root, "parent-alias");
    await symlink(realParent, parentAlias, "dir");
    await expect(readVariantManifest(join(parentAlias, "nested-run", "resume-variants.json"))).rejects.toMatchObject({
      code: "INSECURE_RUN_DIRECTORY",
    });
  });
});
