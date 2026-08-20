# China Targeted Resume

`china-targeted-resume` turns a read-only Markdown career knowledge base into an evidence-grounded resume for a target company and role. It analyzes job requirements, maps source-backed personal evidence, records gaps and constraints, audits visible claims, and renders a local ATS-friendly PDF.

The repository is both:

- a Python 3.14 command-line application; and
- an installable OMP Skill whose orchestration instructions live in [`SKILL.md`](SKILL.md).

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
- A generated PDF is accepted only after deterministic content and PDF checks pass.

## Requirements

- Linux
- Python 3.14 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Playwright Chromium
- Noto Sans CJK SC or Source Han Sans SC installed under `/usr/share/fonts`

On Arch Linux, the font dependency is available as:

```bash
sudo pacman -S --needed noto-fonts-cjk
```

Install project dependencies and Chromium:

```bash
cd /path/to/china-targeted-resume
uv sync
uv run playwright install chromium
```

Confirm that the CLI is available:

```bash
uv run china-targeted-resume --help
```

All examples below use `uv run china-targeted-resume`. If the package is installed globally, omit `uv run`.

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

## Tutorial: generate from a complete current JD

A complete current job description produces a Tier A, `exact-current-jd` analysis. Supply exactly one of `--jd-file`, `--jd-text`, or `--jd-url`.

Using a local UTF-8 JD file:

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description.md \
  --mode targeted_application \
  --language zh-CN \
  --template ats-simple \
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
  --template ats-simple \
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
  --template ats-simple \
  --include-extended-profile \
  --output "$OUTPUT_ROOT"
```

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
  "template": "ats-simple",
  "persist_role_research": false,
  "refresh_external_sources": false,
  "export_roadmap_handoff": false,
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

This command exports confirmed gaps. It does not create a learning plan and does not change current evidence states.

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

- `ats-simple`: conservative single-column ATS layout.
- `human-readable`: the same semantic reading order with a more reader-oriented visual treatment.

## Using the OMP Skill

The installed Skill lets an OMP session interpret natural-language requests and orchestrate the deterministic CLI. The Skill still requires explicit source and output boundaries.

Example prompt:

```text
Use my career knowledge base at /path/to/career-db and the JD at
/path/to/job-description.md to generate the default recruiter and technical
zh-CN ATS resumes for Company A's exact AI Infrastructure Engineer role.
Also include the extended technical profile. Save all artifacts under
/path/to/private-output and report every variant's content and PDF audit results.
```

The Skill should resolve the target tier, run the CLI, ask only material confirmation questions, and report the timestamped run directory. It must not write generated resume text back to `personal-data/`.

## Tests

Run the complete deterministic test suite:

```bash
uv run pytest -q
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
dist/china-targeted-resume.skill
```

The curated `.skill` archive includes runtime code, schemas, references, templates, scripts, `SKILL.md`, and this README. It excludes tests, eval workspaces, caches, real source data, and generated resume outputs.

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

- [`SKILL.md`](SKILL.md): OMP orchestration contract
- [`references/source-adapter.md`](references/source-adapter.md): source discovery and isolation
- [`references/role-resolution.md`](references/role-resolution.md): Tier A-D resolution
- [`references/evidence-policy.md`](references/evidence-policy.md): fact and disclosure gates
- [`references/role-dossier-contract.md`](references/role-dossier-contract.md): seven-file dossier boundaries
- [`references/output-contract.md`](references/output-contract.md): artifact contract
- [`references/resume-audit.md`](references/resume-audit.md): content and PDF acceptance
- [`references/privacy-policy.md`](references/privacy-policy.md): privacy and retention rules
- [`references/roadmap-handoff.md`](references/roadmap-handoff.md): explicit gap export
