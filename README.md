# China Targeted Resume

English | [简体中文](README.zh_CN.md)

`china-targeted-resume` turns a read-only Markdown career knowledge base into an evidence-grounded resume for a target company and role. It analyzes job requirements, maps source-backed personal evidence, records gaps and constraints, audits visible claims, and renders a local ATS-friendly PDF.

The repository provides two separately installed and supported surfaces:

- a standalone Python 3.14 command-line application; and
- an OMP Plugin that bundles the Extension, commands, typed tools, agents, and the canonical Skill at [`skills/china-targeted-resume/SKILL.md`](skills/china-targeted-resume/SKILL.md).

The final runtime decision is **Option A: Plugin-first hybrid**. TypeScript owns OMP integration and the deterministic boundaries covered by cross-language contracts; Python remains the standalone CLI and the explicit parser, composition/audit, Chromium-rendering, and PyMuPDF-inspection backend. Installing the Plugin does not install the Python CLI globally, and installing the Python package does not register the OMP Plugin. See the [final product boundary](docs/final-product-boundary.md) and [Phase 3 parity matrix](docs/parity-matrix.md).

## What it produces

A successful generation creates a new, non-overwriting run directory under the requested output root. The default run contains a recruiter one-page resume and a technical two-page resume:

```text
OUTPUT_ROOT/
└── company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ/
    ├── resume-variants.json
    ├── resume-recruiter-1p.document.json
    ├── resume-recruiter-1p.provenance.json
    ├── resume-recruiter-1p.validation.json
    ├── resume-recruiter-1p.audit.md
    ├── resume-recruiter-1p.md
    ├── resume-recruiter-1p.txt
    ├── resume-recruiter-1p.html
    ├── resume-recruiter-1p.pdf
    ├── resume-recruiter-1p.preview.png
    ├── resume-technical-2p.document.json
    ├── resume-technical-2p.provenance.json
    ├── resume-technical-2p.validation.json
    ├── resume-technical-2p.audit.md
    ├── resume-technical-2p.md
    ├── resume-technical-2p.txt
    ├── resume-technical-2p.html
    ├── resume-technical-2p.pdf
    ├── resume-technical-2p.preview.png
    ├── resume-technical-2p.preview-2.png
    ├── requirements.json
    ├── competencies.json
    ├── evidence-map.json
    ├── gaps.json
    ├── application-constraints.json
    ├── application-recommendation.json
    ├── confirmation-questions.md
    ├── interview-questions.md
    ├── source-manifest.json
    ├── run.json
    └── role-dossier/
```

The first preview page uses `<base>.preview.png`; additional pages use `<base>.preview-2.png`, `<base>.preview-3.png`, and so on. Passing `--include-extended-profile` adds the same per-variant artifact family with base name `technical-profile-3p`. `resume-variants.json` is the authoritative discovery manifest: it lists every generated variant, its page target and actual page count, validation results, artifact paths, and preview paths. Consumers should read the manifest rather than infer filenames.

Runs are not deleted automatically. Each invocation gets a UTC timestamped directory so an earlier run is never silently overwritten.

## Safety model

- The career knowledge base is read-only runtime input.
- The output root must be outside the source root.
- Run directories use mode `0700`; generated files use mode `0600`.
- Persistent indexes contain navigation metadata and hashes, not source bodies or contact data.
- Company research never becomes candidate experience.
- Unverified, conflicting, private, stale, or unsupported claims are omitted or converted into confirmation questions.
- Required-section placement does not by itself make an application constraint a hard gate; `hard_gate` must be assessed explicitly.
- Compound technology requirements need direct evidence for enough of the named technologies. A tech-stack heading or coverage inventory does not prove practical use.
- A generated PDF is accepted only after deterministic content and PDF checks pass.

## Installation and prerequisites

### OMP Plugin

The Plugin compatibility floor is OMP `17.3.7`; it also requires Bun `1.3.0` or newer. A complete generation workflow additionally requires [`uv`](https://docs.astral.sh/uv/) and Python `3.14` or newer because the parser-backed validators, composition/audit, Chromium renderer, and PyMuPDF inspector remain explicit Python backends.

For local development or an unpublished checkout, link the absolute project path:

```bash
omp plugin link /absolute/path/to/china-targeted-resume-plugin --force
```

Install or refresh the published GitHub source with:

```bash
omp plugin install github:ParticleG/china-targeted-resume-plugin
omp plugin install github:ParticleG/china-targeted-resume-plugin --force
```

The GitHub install, recorded `.bun-tag` source/commit, forced refresh, and fresh outside-project `/resume-status` discovery have been verified with OMP `17.3.7`; see `docs/migration-decision-log.md`.

Python-backed Plugin tools run the bundled checkout as `uv run --project PLUGIN_ROOT --offline --frozen china-targeted-resume …`. Provision the locked Python dependencies beforehand, and install Playwright Chromium plus a supported CJK font before rendering. Plugin installation registers OMP components only: it does **not** place `china-targeted-resume` on the global `PATH`, run `uv sync`, or install the browser/fonts. No global CLI installation is required when the project-local bridge command is usable.

## Plugin usage: a five-minute path

This section is the human-facing guide for the installed OMP Plugin. It is intentionally separate from the standalone Python CLI below. The published package is [`ParticleG/china-targeted-resume-plugin`](https://github.com/ParticleG/china-targeted-resume-plugin). Installing it registers the Extension, commands, typed deterministic tools, bundled agents, and Skill; it does **not** provision `uv`, Python, Chromium, CJK fonts, or a global `china-targeted-resume` executable. Use OMP `17.3.7` or newer (and Bun `1.3.0` or newer).

### Five-minute quickstart

1. Install or refresh the published Plugin:

   ```bash
   omp plugin install github:ParticleG/china-targeted-resume-plugin
   ```

2. Ask for local help before starting. Help is rendered through `ctx.ui.notify`; it does not invoke a model. Whether a headless or alternate client displays notifications depends on that client.

   ```text
   /resume-help overview
   ```

3. Initialize a run. Every run starts **metadata-only**:

   ```text
   /resume-init demo-metadata
   ```

4. Discover the read-only source structure:

   ```text
   /resume-discover /tmp/synthetic-career-db
   ```

5. Send the target context to the bundled Skill, then ask the Plugin to analyze and generate. This example uses synthetic paths and requests the default recruiter one-page and technical two-page variants; the optional extended profile is not implied.

   ```text
   Use the bundled china-targeted-resume Skill with source root
   /tmp/synthetic-career-db, the synthetic JD at /tmp/synthetic-jd.md,
   company "Example Company", exact role "Platform Engineer", zh-CN,
   targeted_application mode, ATS output, and output root
   /tmp/private-resume-output. Keep the source read-only and keep output
   outside the source root. Generate the default recruiter one-page and
   technical two-page variants only.

   /resume-analyze demo-metadata
   /resume-generate demo-metadata
   ```

6. Copy the exact `resume-variants.json` path reported by the generation workflow, then inspect every manifest-listed variant and review status:

   ```text
   /resume-audit /tmp/private-resume-output/<run-directory>/resume-variants.json
   /resume-status demo-metadata
   ```

   Replace `<run-directory>` with the timestamped directory actually returned by the Skill. Do not infer a variant from a filename or treat a PDF check as a content-audit result.

### Which command should I use?

| Goal | Command | When to use it | Safe boundary |
| --- | --- | --- | --- |
| Learn the Plugin locally | `/resume-help [topic]` | Before a run or when a stage is unclear | Local notification only; no model, source read, or state mutation |
| Start a run | `/resume-init [run-id] [--reviewed-semantic]` | Once per run, before discovery | Defaults to metadata-only; authorization can only narrow to recorded slices |
| Map a source | `/resume-discover SOURCE_ROOT` | After initialization | Sends a path to the bundled Skill; deterministic discovery returns metadata, not source bodies |
| Analyze a role and evidence | `/resume-analyze [run-id]` | After discovery and whenever analysis must be rebuilt | Starts independent built-in task reviews; never approves claims |
| Compose outputs | `/resume-generate [run-id]` | Only after evidence, approval, and user-confirmation gates are ready | Warns if no lock exists; the deterministic lock and validators still gate composition |
| Inspect generated variants | `/resume-audit RESUME_VARIANTS_JSON` | After generation, or after a rerender | Reads the authoritative manifest and inspects all listed PDFs; no subset can be silently skipped |
| See run state | `/resume-status [run-id\|RESUME_VARIANTS_JSON]` | At any point without exposing source text | Reports metadata, receipts, privacy state, and manifest summary only |

### Command reference

All seven commands accept `-h`, `--help`, or `help` as a local deterministic help request. For example, `/resume-init --help`, `/resume-discover help`, and `/resume-status -h` show usage without invoking the model. These help forms must not be used to smuggle source text into an argument. Paths are bounded path arguments; pass a path, not a pasted Markdown body.
Per-command summary: `/resume-help` takes an optional topic; `/resume-init` takes an optional run ID and `--reviewed-semantic`; `/resume-discover` takes one `SOURCE_ROOT`; `/resume-analyze` and `/resume-generate` take an optional run ID; `/resume-audit` takes one `RESUME_VARIANTS_JSON` path; and `/resume-status` takes an optional run ID or manifest path. There are no other workflow flags.

#### `/resume-help [topic]`

- **Arguments:** optional topic. Without one, use `overview`.
- **Topics:** `overview`, `init`, `discover`, `analyze`, `generate`, `audit`, `status`, `workflow`, `privacy`, `tools`, and `troubleshooting`.
- **Effect:** displays the selected local help topic through `ctx.ui.notify`; it does not initialize a run, call a model, invoke a deterministic tool, or read source content.
- **Example:**

  ```text
  /resume-help workflow
  ```

- **Safe failure:** an unknown topic is reported locally with the available topic list. If a client cannot display notifications, use an interactive OMP client; do not infer that help ran from an empty headless response.

#### `/resume-init [run-id] [--reviewed-semantic]`

- **Arguments:** an optional bounded run ID and the optional `--reviewed-semantic` flag. Without the flag, initialization is metadata-only.
- **Effect:** creates or activates a run state. The flag starts an interactive authorization proposal; it does not automatically disclose a source slice.
- **Example:**

  ```text
  /resume-init demo-metadata
  ```

- **Safe failure:** invalid run IDs, non-interactive UI, missing provider or model identity, a missing OMP session JSONL, or weak ownership/permissions leave the run metadata-only and notify the user. A declined authorization also leaves it metadata-only.

#### `/resume-discover SOURCE_ROOT`

- **Arguments:** exactly one read-only source-root path. Do not pass source text, a JD body, credentials, or a JSON payload in this argument.
- **Effect:** seeds the bundled Skill with a discovery prompt. The Skill calls `resume_discover_structure` to build a fence-aware map of paths, hashes, headings, spans, ancestry, block kinds, and policy metadata.
- **Example:**

  ```text
  /resume-discover /tmp/synthetic-career-db
  ```

- **Safe failure:** an empty, oversized, newline-containing, or otherwise invalid path is rejected locally. A missing/unreadable source or source/output boundary violation fails closed; no source body is sent as a fallback.

#### `/resume-analyze [run-id]`

- **Arguments:** optional run ID; otherwise the active run is used.
- **Effect:** seeds the bundled Skill to run role, requirement, evidence, contribution, and privacy analysis with OMP's built-in `task` fan-out, then asks deterministic IR validators to check the results. It does not approve a claim or create a claim lock.
- **Example:**

  ```text
  /resume-analyze demo-metadata
  ```

- **Safe failure:** an invalid or uninitialized run ID is reported locally. Missing discovery, stale receipts, ambiguous targets, reviewer disagreement, or deterministic validation errors stop the workflow; analysis prose cannot waive them.

#### `/resume-generate [run-id]`

- **Arguments:** optional run ID; otherwise the active run is used.
- **Effect:** seeds the bundled Skill to resolve confirmations, use the exact deterministic approval lock, compose every requested variant, and render artifacts. The default is `resume-recruiter-1p` plus `resume-technical-2p`; an extended `technical-profile-3p` is opt-in only when requested.
- **Example:**

  ```text
  /resume-generate demo-metadata
  ```

- **Safe failure:** if no same-run evidence receipt and approval/claim-lock receipt exist, the command warns and the deterministic workflow remains blocked. It never turns a warning into approval, invents evidence, or pads an underfilled variant.

#### `/resume-audit RESUME_VARIANTS_JSON`

- **Arguments:** exactly one path to the private `resume-variants.json` manifest.
- **Effect:** reads and records the manifest summary, audits retained reviewed-semantic session data when applicable, then seeds the Skill to call `resume_inspect_variants` for every manifest-listed PDF.
- **Example:**

  ```text
  /resume-audit /tmp/private-resume-output/<run-directory>/resume-variants.json
  ```

- **Safe failure:** a missing, malformed, traversal-unsafe, or incomplete manifest fails closed. The command cannot be pointed at one hand-picked PDF to hide another manifest-listed variant.

#### `/resume-status [run-id|RESUME_VARIANTS_JSON]`

- **Arguments:** optional run ID or a `resume-variants.json` path. A `.json` argument is treated as a manifest path; otherwise it is a run ID.
- **Effect:** displays local JSON status for privacy mode, authorization and retention metadata, completed deterministic tools, source/evidence/approval receipts, confirmation count, and manifest summary. It never includes source bodies.
- **Example:**

  ```text
  /resume-status demo-metadata
  /resume-status /tmp/private-resume-output/<run-directory>/resume-variants.json
  ```

- **Safe failure:** invalid IDs or unreadable manifests are reported locally without switching runs or exposing a source body. A status notification is not a success claim.

### Metadata-only example (the default)

Use this mode when structural metadata, hashes, spans, policy values, and deterministic summaries are sufficient. The following is a copyable sequence; replace only the synthetic paths with your own read-only source, JD, and private output paths:

```text
/resume-init demo-metadata
/resume-discover /tmp/synthetic-career-db

Use the bundled Skill. Analyze the exact "Platform Engineer" role at
"Example Company" from /tmp/synthetic-jd.md against /tmp/synthetic-career-db.
Use targeted_application, zh-CN, ats-simple, output root
/tmp/private-resume-output, and generate only the default recruiter one-page
and technical two-page variants.

/resume-analyze demo-metadata
/resume-generate demo-metadata
/resume-status demo-metadata
```

In metadata-only mode, the model and built-in tasks receive IDs, hashes, spans, headings, policy metadata, and deterministic summaries, not source bodies. If a material semantic question cannot be resolved from that information, the Skill must ask a focused question or omit the claim; it must not silently read more.

### Reviewed-semantic initialization (explicit, bounded, and retained)

Use reviewed-semantic mode only when metadata cannot resolve a material decision. Start it interactively:

```text
/resume-init demo-reviewed --reviewed-semantic
```

When prompted, record exact synthetic identities (not credentials), locality, categories, and the smallest useful slices. For example:

```text
Main provider: example-provider
Main model: example-main-model
Main locality: local
Built-in task provider: example-task-provider
Built-in task model: example-task-model
Built-in task locality: local
Authorized disclosure categories: jd,evidence
Exact minimum slices:
[
  {
    "path": "/tmp/synthetic-career-db/roles/example-platform.md",
    "startLine": 8,
    "endLine": 16,
    "category": "jd",
    "consumers": ["main", "role-analyst", "requirement-reviewer"],
    "purpose": "classify the synthetic Platform Engineer requirements"
  },
  {
    "path": "/tmp/synthetic-career-db/projects/example-platform.md",
    "startLine": 42,
    "endLine": 49,
    "category": "evidence",
    "consumers": ["evidence-reviewer", "contribution-reviewer", "privacy-reviewer"],
    "purpose": "verify one synthetic delivery claim and its contribution boundary"
  }
]
```

The authorization disclosure must show the exact main provider/model/locality **and** built-in task provider/model/locality, every category, every slice's path/line bounds/category/consumers/purpose, the observed OMP session JSONL location and permissions, and the retention/cleanup limits. The main session JSONL must be a current-user-owned private regular file with no group/other permissions (normally `0600`); its parent session directory must be a current-user-owned private directory with `0700` and no group/other permissions. The entire OMP task/advisor session tree is audited for ownership, permissions, malformed lines, receipt proof, out-of-scope slices, and forbidden sentinels.

Authorization is per run, provider/model, consumer, category, purpose, and exact span. OMP-owned task and advisor JSONL is retained private data; the Extension has no verified selective-deletion guarantee, so the disclosure must say that plainly. Contacts, credentials, secrets, whole repositories, and F6/P3 content remain forbidden even after authorization. If any interactive or permission gate fails, the run remains metadata-only.

`resume_read_source_slice` is the only bounded body-read path. It rechecks the source-map policy, authorization ID, consumer, provider/model/locality, exact line range, byte limit, and prefilter before returning one slice. Never put a private body in a slash-command argument or claim that a declined/denied read occurred.

### Exact receipt-driven workflow

The Plugin commands seed this state machine; they do not replace it:

```text
init
  → discover
  → source-map receipt
  → analyze/reviews
  → evidence receipt
  → approval receipt
  → compose
  → manifest render
  → inspect/audit
```

Follow the receipts, not filenames or model prose:

1. `/resume-init` establishes metadata-only state, or records the reviewed-semantic authorization.
2. `/resume-discover` leads to `resume_discover_structure`. Run the independent source-mapper and role-analyst tasks through OMP's built-in `task` tool.
3. Call `resume_validate_source_map` and retain its same-run `source_map_receipt.digest`. This validator reopens the source and checks identity, hashes, spans, quotes, and policy.
4. Validate role IR with `resume_validate_role_ir`. Run the independent requirement, evidence, contribution, and privacy reviews. A disagreement is a hard gate, not a vote to ignore.
5. Call `resume_validate_evidence_ir` with the exact `sourceMapDigest` from step 3 and accepted selector IDs or explicitly authorized canonical evidence. Retain its `evidence_receipt.digest`; do not resend a caller-supplied source map.
6. Resolve confirmations and hard gates, then call `resume_lock_approved_claims` with the same-run evidence receipt and unchanged reviewer wrappers. It returns the `approval_receipt`/claim-lock digest; this is the only approval boundary.
7. Call `resume_compose_variants` with the exact evidence and approval receipt digests plus generation-only metadata. It rejects stale, cross-run, output-mode-mismatched, or payload-mismatched receipts.
8. Read `resume-variants.json`, call `resume_render_variants`, then call `resume_inspect_variants` for exactly every listed variant.
9. Report each variant's content-audit result, provenance/privacy checks, PDF inspection, actual pages, and any `underfilled` status separately. A successful PDF inspection is never a substitute for `audit_success`.

The bundled Skill and its seven agents use OMP's built-in `task` orchestration for independent analysis and reviews. Slash commands only seed that workflow and show state; they cannot bypass deterministic source-policy, IR, evidence, approval, composition, rendering, or inspection tools.

### Ten deterministic tools by user-facing stage

| Stage | Tool | What it does and what it refuses |
| --- | --- | --- |
| Discover | `resume_discover_structure` | Builds the metadata-only source map (paths, hashes, spans, headings, ancestry, blocks, policy); never exposes bodies or orchestrates agents |
| Bounded exposure | `resume_read_source_slice` | Reads one exact authorized, prefiltered line slice only in reviewed-semantic mode; metadata-only runs and unapproved, unrelated, forbidden, oversized, or mismatched slices fail closed |
| Source-map validation | `resume_validate_source_map` | Reopens source and verifies identity, hashes, spans, quotes, and policy; agent output cannot override it and it records the source-policy receipt |
| Role validation | `resume_validate_role_ir` | Checks normalized role IR, requirement quotes/spans, freshness, and company/role/roadmap separation |
| Evidence validation | `resume_validate_evidence_ir` | Materializes only approved extractive IDs in metadata-only mode or validates an authorized canonical evidence IR; returns an evidence receipt and rejects caller-supplied source maps |
| Approval | `resume_lock_approved_claims` | Applies hard-disagreement rules, verifies reviewer wrappers and revalidated sources, collects required user confirmations, and creates the claim lock; caller booleans/evidence bodies are forbidden |
| Compose | `resume_compose_variants` | Verifies same-run receipts and confirmation state, then invokes private Python composition; it cannot receive caller-supplied evidence/review/approval bodies |
| Render | `resume_render_variants` | Re-renders every manifest-listed document to its manifest-listed PDF; traversal-unsafe or missing artifacts fail closed |
| Inspect/audit | `resume_inspect_variants` | Inspects every manifest-listed PDF with its page contract and real extracted-text checks; a subset cannot be supplied |
| Growth roadmap | `resume_write_growth_roadmap` | Routes the independent roadmap Skill through the bundled locked Python project; validates the handoff-bound plan and writes private non-overwriting artifacts without requiring a global CLI |

All tools return a typed success/error envelope and use one configured backend. There is no silent TypeScript/Python fallback. Python-backed tools require the project-local bridge prerequisites.

### Discovering artifacts and the authoritative manifest

Generation always creates `resume-recruiter-1p` and `resume-technical-2p`. Ask for `technical-profile-3p` only when an extended profile is useful; it is not part of the default. The Skill writes a new timestamped run directory under the private output root. `resume-variants.json` is authoritative and lists each variant's target and actual page counts, validation/audit results, artifact paths, and preview paths. Read it first:

```text
RUN_DIR/resume-variants.json
```

Then open only paths listed for that variant, such as its `.document.json`, `.provenance.json`, `.validation.json`, `.audit.md`, `.md`, `.txt`, `.html`, `.pdf`, and preview images. The manifest may legitimately mark a sparse variant `underfilled`; do not add unsupported filler merely to reach the page target. Each manifest-listed variant must pass content audit and PDF inspection independently. PDF pass, page count, or file existence alone never means content audit passed.

### Plugin prerequisites and privacy gates at a glance

- OMP `17.3.7+`, Bun `1.3.0+`, `uv`, and Python `3.14+` are required for the complete Plugin workflow.
- The bundled bridge uses `uv run --project PLUGIN_ROOT --offline --frozen`; install the locked dependencies before invoking Python-backed tools.
- Playwright Chromium and Noto Sans CJK SC or Source Han Sans SC under `/usr/share/fonts` are required for rendering; Plugin installation does not install either.
- Keep the source read-only and keep the output root outside it. Runtime directories/files are private (`0700`/`0600`).
- Metadata-only is the default. Reviewed-semantic mode additionally requires an interactive UI, explicit per-run authorization, and a strong private OMP session tree.
- Do not disclose contacts, credentials, secrets, or F6/P3 material. Do not infer permission from an earlier run or from CLI access.

### Plugin troubleshooting

#### “No deterministic claim-lock result is recorded”

`/resume-generate` may warn about this state, but it cannot approve claims. Return to `/resume-analyze`, ensure the same run has a successful source-map and evidence receipt, resolve independent reviewer disagreements and required confirmations, and let the Skill call `resume_lock_approved_claims`. Do not paste evidence or approval JSON into `/resume-generate`, and do not treat the warning as success.

#### `SOURCE_POLICY_REQUIRED` or an unrelated slice

The evidence tool or slice reader is missing the same-run validated source-policy receipt, or the requested path/span is not in the authorized policy map/minimum-slice list. Re-run discovery and `resume_validate_source_map`, use its returned digest, and request only the exact authorized span with its recorded consumer/category/purpose. Never widen a slice, substitute a different file, or paste the source body into a command argument.

#### Weak OMP session tree

Reviewed-semantic authorization stays disabled when the JSONL file or any audited task/advisor directory/file is not current-user-owned, private, regular, or receipt-proven. Fix the OMP session directory/file permissions and ownership, start a fresh private interactive session if needed, and initialize a new run. A weak tree, `outOfScopeSliceCount`, `forbiddenSentinelCount`, malformed lines, or retained-artifact audit failure must be reported; never claim cleanup or deletion that was not demonstrated.

#### Missing Python bridge dependencies

Plugin installation does not run dependency setup. From the checkout, provision the locked environment and rendering prerequisites before using Python-backed tools:

```bash
cd /path/to/china-targeted-resume-plugin
uv sync
uv run playwright install chromium
```

Install Noto Sans CJK SC or Source Han Sans SC under `/usr/share/fonts` as described in the prerequisites. The bridge intentionally runs offline/frozen from the bundled project; a missing package, browser, or font is an explicit backend failure, not a reason to bypass the deterministic tool.

#### `audit_success` is false or a variant is `underfilled`

Read `resume-variants.json`, then the affected variant's `.validation.json` and `.audit.md`. Fix the source-backed claim, policy, privacy, layout, or rendering issue and rerun the affected deterministic stages. `underfilled` can be a valid sparse-evidence result with fewer actual pages; do not pad it or silently add the optional extended profile. A PDF that passes page/text inspection can still have `audit_success: false`, and `audit_success: true` does not remove the need to inspect the real PDF.

### Standalone Python CLI

The CLI does not require OMP or the Plugin. It requires:

- Linux;
- Python 3.14 or newer;
- [`uv`](https://docs.astral.sh/uv/);
- Playwright Chromium; and
- Noto Sans CJK SC or Source Han Sans SC installed under `/usr/share/fonts`.

On Arch Linux, the font dependency is available as:

```bash
sudo pacman -S --needed noto-fonts-cjk
```

Install project dependencies and Chromium:

```bash
cd /path/to/china-targeted-resume-plugin
uv sync
uv run playwright install chromium
```

Confirm that the project-local CLI is available:

```bash
uv run china-targeted-resume --help
```

All CLI examples below use `uv run china-targeted-resume`. Omit `uv run` only when the Python package has been installed independently as a global command.

## Tutorial: prepare source and output paths

Set paths once for the current shell:

```bash
export SOURCE_ROOT=/path/to/read-only-career-knowledge-base
export OUTPUT_ROOT=/path/to/private-resume-output
```

`OUTPUT_ROOT` must not be equal to, or located below, `SOURCE_ROOT`.


## Tutorial: discover companies and roles

List companies recognized by the source adapter:

```bash
uv run china-targeted-resume list-companies \
  --source "$SOURCE_ROOT"
```

List roles for one exact company ID or display name:

```bash
uv run china-targeted-resume list-roles \
  --source "$SOURCE_ROOT" \
  --company COMPANY
```

Use the returned identifiers in later commands. If multiple companies or roles match, select one explicitly rather than guessing.

## Tutorial: guided standalone generation

When OMP is unavailable, `guided-generate` removes the manual company/role discovery choreography. It accepts either the career repository root or a conventional child such as `company-research`, writes interactive choices and prompts only to a dedicated terminal device, and keeps the final machine-readable result on stdout. Expected failures remain one JSON object on stderr; non-interactive callers must pass exact `--company` and `--role` values.

```bash
uv run china-targeted-resume guided-generate \
  --source "$SOURCE_ROOT/company-research" \
  --jd-file /path/to/job-description.md \
  --output "$OUTPUT_ROOT"
```

Pass `--company` or `--role` to skip either prompt. The default `adaptive` strategy selects the concrete single-column template per variant and records it in `resume-variants.json`.

## Tutorial: generate from a complete current JD

A supplied, non-empty job description is treated as complete by default and produces a Tier A, `exact-current-jd` analysis. Supply one—and only one—of `--jd-file`, `--jd-text`, or `--jd-url`. `--company` and `--role` may be omitted when the JD itself is the authoritative target input, although exact source identifiers improve target naming and source joins.

Using a local UTF-8 JD file:

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description.md \
  --mode targeted_application \
  --language zh-CN \
  --template adaptive \
  --output "$OUTPUT_ROOT"
```

Using an HTTPS JD URL:

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-url https://jobs.example.invalid/ROLE \
  --mode targeted_application \
  --language zh-CN \
  --template adaptive \
  --output "$OUTPUT_ROOT"
```

The command prints JSON containing `run_dir` and the generated artifact paths. Keep `run_dir`; follow-up validation and refresh commands use it.

Generation always emits `resume-recruiter-1p` and `resume-technical-2p`. To also emit the extended three-page profile, add:

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description.md \
  --mode targeted_application \
  --language zh-CN \
  --template adaptive \
  --include-extended-profile \
  --output "$OUTPUT_ROOT"
```

## Tutorial: use an incomplete JD excerpt and independent constraints

A supplied JD defaults to complete. Add `--jd-incomplete` only when the supplied text, file, or URL is an excerpt. The flag requires one JD source. With an exact company and role, the parser still extracts explicit requirements from the excerpt, but target resolution remains Tier B and coverage stays indeterminate:

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description-excerpt.md \
  --jd-incomplete \
  --application-constraints-file /path/to/application-constraints.json \
  --mode targeted_application \
  --output "$OUTPUT_ROOT"
```

`--application-constraints-file` must contain one private JSON array conforming to [`schemas/application-constraints.schema.json`](schemas/application-constraints.schema.json). A non-empty array replaces the constraints parsed from the JD; an empty array preserves the parsed set. Use it only for independently assessed logistics and eligibility such as location, work authorization, language, travel, schedule, deadline, or mandatory checks. Set `hard_gate` from the specific constraint semantics and supporting assessment, not merely because text appeared under a “required” heading. Experience, seniority, capability, and skill thresholds are rejected here.

Experience duration and skill thresholds are requirements, not application constraints. Duration diagnostics use a two-run, non-overwriting flow so every input binds to IDs produced by the deterministic requirement and evidence mapping stages:

1. Run `generate` or `guided-generate` once without a duration diagnostics file.
2. Read the resulting `requirements.json`, `evidence-map.json`, and private `experience-duration-facts.json`. The explicit requirement must contain a parser-owned duration from its quote; the candidate fact index lists only evidence IDs whose current owning path/hash/span yielded one extractive atomic duration plus checked date.
3. Create a private `duration-diagnostics.json` using the exact requirement ID and an evidence ID from that candidate fact index:

```json
[
  {
    "requirement_id": "REQ-PYTHON-YEARS",
    "diagnostic": {
      "candidate_scope": "professional Python development",
      "required_scope": "professional Python development",
      "unit": "years",
      "candidate_years": 4,
      "required_min_years": 5,
      "evidence_refs": ["ev-python-duration"],
      "checked_at": "2026-08-30T00:00:00Z"
    }
  }
]
```

4. Rerun the same generation command into the same output root, adding:

```bash
--experience-duration-diagnostics-file /path/to/duration-diagnostics.json
```

The new timestamped run rebuilds current `EvidenceRecord` objects by reopening their owning source sections and validating source path, hash, and span. A referenced record must contain one extractive atomic candidate fact such as `4 years of professional Python development experience; checked 2026-08-30`; the parser owns its scope, years, and check time. The binding's `candidate_scope`, `candidate_years`, and `checked_at` must exactly match every referenced record fact, so an arbitrary selected evidence ID or self-reported number is rejected. The required scope/minimum/maximum must likewise equal the structure parsed from the explicit requirement quote/span; changing an 8-year JD threshold to 5 years is rejected. Compound scopes, free text, missing audit data, inferred requirements, altered thresholds, or evidence without a matching owning duration fact cannot use the tolerance.

## Tutorial: generate when only the role is known

If no complete current JD is available, omit all JD options. The pipeline continues as Tier B when the source contains an exact role and dated company research:

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --mode targeted_application \
  --language zh-CN \
  --template human-readable \
  --output "$OUTPUT_ROOT"
```

Tier B output records source age, missing requirements, conflicts, inference emphasis, and coverage limitations in audit artifacts rather than presenting them as resume facts.

The command surface keeps `--company` and `--role` optional so a complete JD or `master_resume` can drive generation without a source target reference. Without a complete JD, `targeted_application` and `public_portfolio` require sufficient target identity; a Tier D request fails with machine-readable `selection_required` choices. Only `master_resume` accepts Tier D, and it must not present role-specific fit conclusions.

## Tutorial: inspect a completed run

Set the exact timestamped directory returned by `generate`:

```bash
export RUN_DIR="$OUTPUT_ROOT/company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ"
```

Run content audits again:

```bash
uv run china-targeted-resume validate-content \
  --run "$RUN_DIR"
```

Inspect each generated PDF independently with its exact page ceiling:

```bash
uv run china-targeted-resume inspect-pdf \
  --pdf "$RUN_DIR/resume-recruiter-1p.pdf" \
  --max-pages 1 \
  --expected-name "CANDIDATE NAME"

uv run china-targeted-resume inspect-pdf \
  --pdf "$RUN_DIR/resume-technical-2p.pdf" \
  --max-pages 2 \
  --expected-name "CANDIDATE NAME"
```

If the extended profile was requested, inspect `technical-profile-3p.pdf` with `--max-pages 3`.

Use `resume-variants.json` to discover the variants and open each variant's Markdown, PDF, previews, audit, provenance, and validation JSON. For example:

```text
RUN_DIR/resume-variants.json
RUN_DIR/resume-recruiter-1p.pdf
RUN_DIR/resume-recruiter-1p.validation.json
RUN_DIR/resume-technical-2p.pdf
RUN_DIR/resume-technical-2p.validation.json
```

A run is complete only when every listed variant has a successful content audit and PDF inspection, and every preview has no clipping, overlap, broken CJK text, malformed bullets, or audit/provenance language in visible resume sections.

## Tutorial: rebuild individual stages

Rebuild the deterministic evidence map:

```bash
uv run china-targeted-resume build-evidence-map \
  --run "$RUN_DIR"
```

Render one existing variant document again:

```bash
uv run china-targeted-resume render \
  --document "$RUN_DIR/resume-technical-2p.document.json" \
  --output "$RUN_DIR/resume-technical-2p.pdf"
```

The output directory must remain private and must not traverse a symlink. After rendering, inspect that PDF with the variant's exact `--max-pages` value.

## Standalone CLI: deterministic IR boundaries

The standalone CLI exposes the parser-backed intermediate-representation (IR) boundaries used by the Plugin bridge. These commands are deterministic validation stages, not shortcuts around source, review, privacy, approval, or provenance gates:

| Command | Boundary enforced |
| --- | --- |
| `discover-source-structure` | Builds a fence-aware, metadata-only source map from a read-only source root. |
| `validate-source-map` | Re-opens the source and verifies source identity, hashes, spans, exact quotes, and policy metadata. |
| `validate-role-input` | Validates normalized role IR while keeping requirements, company research, roadmap content, constraints, and candidate evidence separate. |
| `validate-evidence-input` | Validates source-backed normalized evidence IR or performs explicitly requested bounded extractive materialization. |
| `approve-claims` | Revalidates evidence, requires `review_decisions`, and emits the exact deterministically approved claim set. |
| `generate-from-ir` | Revalidates the complete generation bundle, recomputes approvals, checks provenance closure, and composes variants only from locked claim text. |

Except for discovery, each stage reads one JSON object from `--input FILE` or stdin and writes JSON to `--output FILE` or stdout. `validate-role-input`, `validate-evidence-input`, and `approve-claims` require `--source`; `generate-from-ir` requires `source_root` and `output_root` either in its input metadata or through `--source` and `--output-root`. Its `--output` option is the stage-result JSON path, not the resume artifact root.

```bash
uv run china-targeted-resume discover-source-structure \
  --source "$SOURCE_ROOT" \
  --output /path/to/private/source-map.json

uv run china-targeted-resume validate-source-map \
  --source "$SOURCE_ROOT" \
  --input /path/to/private/source-map.json \
  --output /path/to/private/validated-source-map.json

uv run china-targeted-resume generate-from-ir \
  --input /path/to/private/generation-bundle.json \
  --source "$SOURCE_ROOT" \
  --output-root "$OUTPUT_ROOT"
```

`generate-from-ir` does not accept an approved-claims document alone. Its input bundle must also carry the source map, normalized evidence, review decisions, approved safe-claim selections, and user confirmations needed to reproduce the approval result exactly.

## Tutorial: analyze a request JSON

`analyze-role` accepts a validated `RunRequest` JSON document. See [`schemas/request.schema.json`](schemas/request.schema.json) for the complete contract.

Example:

```json
{
  "schema_version": 1,
  "source_adapter": "markdown-career-v1",
  "source_root": "/path/to/read-only-career-knowledge-base",
  "output_root": "/path/to/private-resume-output",
  "company_ref": "COMPANY",
  "role_ref": "ROLE TITLE",
  "jd": {
    "text": null,
    "file": "/path/to/job-description.md",
    "url": null
  },
  "output_mode": "targeted_application",
  "language": "zh-CN",
  "include_extended_profile": false,
  "template": "adaptive",
  "persist_role_research": false,
  "refresh_external_sources": false,
  "export_roadmap_handoff": false,
  "experience_duration_diagnostics": [],
  "application_constraints": {}
}
```

Run the analysis:

```bash
uv run china-targeted-resume analyze-role \
  --request /path/to/request.json
```

The dossier remains run-local unless persistence into the source repository is explicitly reviewed and approved.

## Tutorial: refresh role or evidence analysis

Refresh role analysis after the JD or company research changes:

```bash
uv run china-targeted-resume refresh-role \
  --role "$RUN_DIR"
```

Refresh evidence mappings after an owning personal-data source changes:

```bash
uv run china-targeted-resume refresh-match \
  --role "$RUN_DIR"
```

Refresh operations create new non-overwriting output rather than rewriting the source knowledge base. A roadmap entry never promotes a match state; verified work must first be recorded in the correct personal-data owner.

## Tutorial: export confirmed gaps

Roadmap handoff is explicit and one-way. Export it only after reviewing the gaps and deciding to create a separate learning plan:

```bash
uv run china-targeted-resume export-roadmap-handoff \
  --role "$RUN_DIR" \
  --severity Critical,Major \
  --output "$RUN_DIR/roadmap-handoff.json"
```

This command exports confirmed gaps. It does not create a learning plan and does not change current evidence states. Give the resulting file to the separately installed `china-resume-growth-roadmap` Skill only after an explicit planning request.

The independent Skill prepares a private plan conforming to [`schemas/growth-roadmap.schema.json`](schemas/growth-roadmap.schema.json). In Plugin mode it calls `resume_write_growth_roadmap`, which routes through the bundled locked Python project and does not require a global CLI. On the separately installed standalone surface, use:

```bash
uv run china-targeted-resume write-growth-roadmap \
  --source "$SOURCE_ROOT" \
  --handoff "$RUN_DIR/roadmap-handoff.json" \
  --plan /path/to/private/draft-growth-roadmap.json \
  --output "$OUTPUT_ROOT"
```

The writer verifies the exact handoff hash and every preserved gap field—including `priority_reason`, `suggested_artifacts`, and `verification_signals`—requires all six stages and at least one current HTTPS learning resource per plan, rejects permissive/symlinked/oversized inputs, validates the output boundary, creates a new non-overwriting `0700` run directory, and atomically writes three `0600` artifacts: JSON, Markdown, and a validation receipt.

## Output modes, variants, and templates

Output modes:

- `targeted_application`: permits confirmed application-only P2 evidence.
- `public_portfolio`: excludes application-only material and private contact details where required.
- `master_resume`: builds a broader evidence-backed resume without pretending that an insufficient target is an exact role.

Variants:

- `resume-recruiter-1p`: concise one-page recruiter scan, always generated.
- `resume-technical-2p`: two-page technical resume, always generated.
- `technical-profile-3p`: extended three-page technical profile, generated only with `--include-extended-profile`.

Each variant is composed independently for its reader and configured page target; it is not one document rendered at several arbitrary page limits. When source evidence is too sparse to support the target without padding, the manifest marks the variant `underfilled` and the validated PDF may use fewer pages.

Templates:

- `adaptive` (default): `ats-simple` for the recruiter one-page variant and `human-readable` for the technical two-page and optional extended three-page variants.
- `ats-simple`: conservative semantic single-column ATS layout for every variant.
- `human-readable`: the same semantic single-column reading order with a more reader-oriented visual treatment for every variant.

Multi-column rendering is intentionally unsupported because it can make extraction order ambiguous. Page-count variants instead differ through evidence budget, density, typography, and reader emphasis.

## Using the OMP Plugin and Skill

The installed Plugin lets an OMP session interpret natural-language requests through a **Plugin-first hybrid** backend. Start with `/resume-init`, then use `/resume-discover`, `/resume-analyze`, `/resume-generate`, `/resume-audit`, and `/resume-status` as appropriate. These commands are orchestration entry points, not replacements for policy validation.

Every Plugin tool has one configured backend and fails explicitly if that backend is unavailable; there is no silent Python/TypeScript fallback. TypeScript handles the authorized source-slice reader and approved-claim lock, while the `markdown-it-py` source-map/role/evidence validators, composition and audit, Playwright Chromium rendering, and PyMuPDF inspection remain explicit Python-backed tools. The complete per-tool matrix is in [`docs/final-product-boundary.md`](docs/final-product-boundary.md).

Every run starts in metadata-only mode: models receive structural metadata, IDs, hashes, spans, policy values, and deterministic summaries, not source bodies. If a material semantic decision needs an exact private slice, the Plugin must first disclose the selected provider and locality, the category and minimum proposed slices, the private OMP JSONL location and observed permissions, and the retention/cleanup limits. Reviewed-semantic access requires explicit authorization for that run. Contacts, credentials, and F6/P3 content remain forbidden.

The Skill directs the main model to fan out the seven bundled agents with OMP's built-in `task` tool. Independent requirement, evidence, contribution, and privacy disagreements are hard gates; the resume advisor is a workflow watchdog and cannot approve claims. Parser-backed validation runs before the TypeScript approved-claim lock, and only exact locked claims may be composed, rendered, and inspected.

Example prompt:

```text
Use my career knowledge base at /path/to/career-db and the JD at
/path/to/job-description.md to generate the default recruiter and technical
zh-CN ATS resumes for Company A's exact AI Infrastructure Engineer role.
Also include the extended technical profile. Save all artifacts under
/path/to/private-output and report every variant's content and PDF audit results.
```

The Skill resolves the target tier, asks only material confirmation questions, and reports the timestamped run directory. It never writes generated resume text back to `personal-data/`. A Plugin or `.skill` installation alone does not install the Python CLI; the project-local kernel bridge prerequisites above must already be usable.

## Tests

Run the standalone Python and real-artifact suite:

```bash
uv run pytest -q
```

Run the Plugin typecheck and complete Bun contract suite:

```bash
bun run check
```

For a focused Phase 3 schema, secure-I/O, and source-identity gate:

```bash
bun run test:kernel
```

## Build and package

Build the Python distributions and curated Skill archive:

```bash
uv build
uv run python scripts/package_skill.py
```

Expected artifacts:

```text
dist/china_targeted_resume-0.1.0.tar.gz
dist/china_targeted_resume-0.1.0-py3-none-any.whl
dist/china-targeted-resume-plugin.skill
```

The Git/source OMP Plugin package follows `package.json#files`: it includes the Extension, deterministic TypeScript kernel, agents, canonical Skill, schemas, assets, Python specialist backend, locked Python project metadata, and the final boundary/parity documentation. It does not include tests. The Python wheel contains the standalone runtime, rendering assets, and the five IR schemas needed by installed validation commands. The sdist contains the canonical Plugin-layout Skill and its references. The curated `.skill` archive consumes that same canonical source, stages one root `SKILL.md` plus `references/`, and includes Python runtime source, schemas, templates, scripts, and this README without recursive `.agents/skills` or `.claude/skills` links. It excludes tests, eval workspaces, caches, real source data, and generated resume outputs.

These are different installation artifacts: neither installing the OMP Plugin nor unpacking the `.skill` archive performs a global Python CLI installation. The `.skill` archive is an orchestration bundle, not the OMP Extension package.

## Evaluation workspace

A sibling directory such as:

```text
<project-parent>/china-targeted-resume-workspace
```

is created by the Skill Creator evaluation workflow. It contains iteration outputs, with-Skill/baseline comparisons, grading, timing, benchmark data, and `review.html`. It is not imported by the Python package, is not included in the `.skill` archive, and is not required to run the CLI or installed Skill.

Keep it when you need reproducible benchmark history. Archive or delete it only when those evaluation records are no longer needed.

## Finding generated runs

Generated resumes are stored under the `--output` root, not under the project repository and not under the evaluation workspace.

For example:

```text
<output-root>/
└── company-slug--role-slug--YYYYMMDDTHHMMSSffffffZ/
```

Each run contains shared analysis artifacts plus independently composed resume variants. Discover them through `resume-variants.json`; each listed variant has its own document, Markdown, ATS text, HTML, PDF, previews, provenance, audit, and validation report.

If a file manager does not show the directory:

1. paste the full absolute path into its location bar;
2. refresh the parent directory;
3. confirm that you opened the exact root passed through `--output`; and
4. run `stat` on the full path from a terminal.

## Troubleshooting

### Chromium executable is missing

```bash
uv run playwright install chromium
```

### CJK font is missing

Install Noto Sans CJK SC or Source Han Sans SC under `/usr/share/fonts`. On Arch Linux:

```bash
sudo pacman -S --needed noto-fonts-cjk
```

### Output overlaps the source

Choose an output root outside the career knowledge base. The source and output must not be the same path, and output must not be a descendant of source.

### Existing output root has broad permissions

Use a private output directory:

```bash
chmod 700 "$OUTPUT_ROOT"
```

Generated files are automatically restricted to mode `0600`.

### Company or role is ambiguous

Run `list-companies` and `list-roles`, then pass an exact returned identifier. The pipeline intentionally does not guess among multiple matches.

### A PDF exists but validation fails

Open `resume-variants.json`, then read the failing variant's `<base>.validation.json` and `<base>.audit.md`. Fix source-backed content or rendering problems, rerun `validate-content`, render the affected `<base>.document.json`, and inspect its PDF with the exact page ceiling (`1`, `2`, or `3`). File existence alone is not acceptance.

## Further documentation

- [`docs/final-product-boundary.md`](docs/final-product-boundary.md): Option A runtime decision, supported runtimes, installation/update gates, and per-tool backend ownership
- [`docs/parity-matrix.md`](docs/parity-matrix.md): Phase 3 parity evidence, exact normalization policy, and final verification matrix
- [`skills/china-targeted-resume/SKILL.md`](skills/china-targeted-resume/SKILL.md): canonical OMP orchestration contract
- [`skills/china-targeted-resume/references/source-adapter.md`](skills/china-targeted-resume/references/source-adapter.md): source discovery and isolation
- [`skills/china-targeted-resume/references/role-resolution.md`](skills/china-targeted-resume/references/role-resolution.md): Tier A-D resolution
- [`skills/china-targeted-resume/references/evidence-policy.md`](skills/china-targeted-resume/references/evidence-policy.md): fact and disclosure gates
- [`skills/china-targeted-resume/references/role-dossier-contract.md`](skills/china-targeted-resume/references/role-dossier-contract.md): seven-file dossier boundaries
- [`skills/china-targeted-resume/references/output-contract.md`](skills/china-targeted-resume/references/output-contract.md): artifact contract
- [`skills/china-targeted-resume/references/resume-audit.md`](skills/china-targeted-resume/references/resume-audit.md): content and PDF acceptance
- [`skills/china-targeted-resume/references/privacy-policy.md`](skills/china-targeted-resume/references/privacy-policy.md): privacy and retention rules
- [`skills/china-targeted-resume/references/roadmap-handoff.md`](skills/china-targeted-resume/references/roadmap-handoff.md): explicit gap export
- [`skills/china-targeted-resume/references/social-hire-writing.md`](skills/china-targeted-resume/references/social-hire-writing.md): experienced-hire relevance, verbs, terminology, metrics, and structured near-match rules
- [`skills/china-targeted-resume/references/public-resume-patterns.md`](skills/china-targeted-resume/references/public-resume-patterns.md): public examples and evidence-safe adaptation patterns
- [`skills/china-resume-growth-roadmap/SKILL.md`](skills/china-resume-growth-roadmap/SKILL.md): independent staged growth-plan workflow for an explicit roadmap handoff
