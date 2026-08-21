# Repository Guidelines

## Project Overview

`china-targeted-resume` is both a Python 3.14 command-line application and an installable OMP Skill. It converts a read-only Markdown career knowledge base into evidence-grounded resumes for target companies and roles in China, then produces ATS text, Markdown, HTML, PDF, audit, provenance, gap, and role-dossier artifacts.

The core is deterministic: source discovery, requirement analysis, evidence mapping, policy checks, composition, rendering, and PDF inspection do not depend on an LLM. Preserve these invariants:

- Never modify the source knowledge base at runtime.
- Keep `output_root` outside `source_root`.
- Create timestamped, non-overwriting run directories.
- Do not promote company research, plans, stale data, or unverified claims into candidate evidence.
- Keep generated directories/files private (`0700`/`0600`).

## Architecture & Data Flow

1. `src/china_targeted_resume/cli.py` parses subcommands into strict Pydantic request models. Successful output is JSON on stdout; expected user errors are JSON on stderr with exit status 2.
2. `src/china_targeted_resume/pipeline.py::Pipeline` validates source/output boundaries and orchestrates domain modules. Its `adapter_factory` constructor argument is the primary dependency-injection seam.
3. `adapters/markdown_career_v1.py` discovers companies, roles, policies, and metadata. Retrieval is two-stage: metadata/title/heading discovery, then minimal owning-section reads. Persistent manifests contain hashes and navigation metadata, not source bodies.
4. `target_resolution.py` assigns Tier A-D target context. `role_analysis/` parses job descriptions, classifies requirements, detects anomalies, and builds competencies. Requirements, competencies, application constraints, and candidate evidence remain separate models.
5. `evidence.py`, `policy.py`, `constraints.py`, `gaps.py`, and `application_advice.py` validate source-backed evidence, apply F1-F6/P0-P3 disclosure gates, map canonical match states, derive gaps, and create recommendations. Visible claims must retain provenance IDs.
6. `dossier.py` writes the run-local seven-file role dossier. `composition.py` converts eligible records into the canonical `ResumeDocument`; `audit.py` validates truthfulness, privacy, ATS structure, and provenance.
7. `rendering/html.py` renders local Jinja templates; `rendering/pdf.py` uses headless Chromium; `rendering/inspect.py` checks the real PDF and preview. Semantic compaction removes lower-priority content before violating minimum font or margin constraints.
8. `io.py` owns path-boundary checks, private directory creation, atomic writes, and non-overwriting run allocation. Use these helpers instead of ad hoc file writes.

`skills/china-targeted-resume/SKILL.md` is the canonical natural-language orchestration layer, and its colocated `references/` directory owns detailed policy and data contracts. Authority is boundary-specific: root Draft 2020-12 schemas and the deterministic TypeScript kernel own ported contracts; Python remains executable authority for Markdown parsing, composition/audit, Chromium rendering, PDF inspection, and the standalone CLI. See `docs/final-product-boundary.md`.

## Key Directories

| Path | Purpose |
| --- | --- |
| `src/china_targeted_resume/` | CLI, orchestration, domain models, evidence policy, composition, audit, and secure I/O. |
| `src/plugin/` | OMP Extension registration, commands, typed tools, privacy state, explicit backend routing, and the Python bridge. |
| `src/kernel/` | Deterministic TypeScript schema, secure-I/O, source-identity, policy/approval, and provenance contracts that have an explicit Phase 3 boundary. |
| `src/china_targeted_resume/adapters/` | Read-only career-source adapters; `markdown_career_v1.py` is the current implementation. |
| `src/china_targeted_resume/role_analysis/` | JD parsing, requirement classification, anomaly detection, and competency construction. |
| `src/china_targeted_resume/rendering/` | HTML rendering, Chromium PDF generation, compaction, and PDF inspection. |
| `assets/templates/` | Local Jinja templates: `ats-simple` and `human-readable`. |
| `assets/styles/` | Shared A4/CJK layout plus template-specific themes. |
| `schemas/` | Strict JSON Schema Draft 2020-12 contracts for requests, dossiers, evidence, documents, and reports. |
| `scripts/` | Source-index, evidence-validation, PDF, inspection, and Skill-packaging entry points. |
| `skills/china-targeted-resume/` | Canonical OMP Skill and its architecture, privacy, evidence, dossier, audit, output, and roadmap-handoff references. |
| `tests/` | Flat pytest contract suite and fully synthetic Markdown career database. |
| `evals/` | OMP Skill scenarios and trigger-classification fixtures/results; not runtime code. |

## Development Commands

Run commands from the repository root. Bun owns Plugin/TypeScript checks; `uv` owns Python:

```bash
bun run check
bun run test:kernel
uv sync
uv run playwright install chromium
uv run china-targeted-resume --help
uv run pytest -q
uv build
uv run python scripts/package_skill.py
```

Typical end-to-end generation:

```bash
uv run china-targeted-resume generate \
  --source "$SOURCE_ROOT" \
  --company COMPANY \
  --role "ROLE TITLE" \
  --jd-file /path/to/job-description.md \
  --mode targeted_application \
  --language zh-CN \
  --pages 2 \
  --template ats-simple \
  --output "$OUTPUT_ROOT"
```

Useful staged commands are `list-companies`, `list-roles`, `analyze-role`, `build-evidence-map`, `validate-content`, `render`, `inspect-pdf`, `refresh-role`, `refresh-match`, and `export-roadmap-handoff`; inspect their exact arguments with `--help`.

Prefer the top-level CLI. The similarly named `scripts/render_pdf.py`, `scripts/inspect_pdf.py`, and `scripts/validate_evidence.py` accept one positional JSON file or JSON on stdin, not the top-level CLI flags.

TypeScript uses the configured `tsc --noEmit` check. No formatter or linter is configured, and Python has no static type checker configured. Do not invent Ruff, Black, Mypy, Pyright, line-length, or coverage-threshold requirements.

## Code Conventions & Common Patterns

- Use `from __future__ import annotations`, complete type hints, `pathlib.Path`, snake_case functions/modules, PascalCase classes, and leading underscores for private helpers.
- Model external and cross-module data with subclasses of `models.CanonicalModel`. These use Pydantic `extra="forbid"` and assignment validation; prefer enums and field constraints over stringly typed dictionaries.
- Keep domain rules in focused modules and let `Pipeline` compose them. Do not duplicate policy logic in CLI handlers, templates, or scripts.
- The application is synchronous. There is no asyncio/task state model; pass inputs explicitly and return Pydantic models, frozen/slotted dataclasses, or plain deterministic values.
- Treat run artifacts as explicit state. Avoid module-level mutable state, hidden caches, implicit network calls, and writes outside the requested output tree.
- Fail closed at trust boundaries. Raise specific domain or validation errors (`PipelineError`, `SelectionRequired`, `OutputBoundaryError`, `ValidationError`, or `ValueError`) and let the CLI translate expected failures into machine-readable JSON.
- Preserve stable IDs, source hashes, source spans, evidence IDs, claim IDs, and provenance links through transformations. Targeting may change selection/order, never the underlying fact wording or attribution.
- Use secure atomic writers from `io.py`. Do not replace private modes, source/output separation, symlink/path traversal checks, or non-overwriting semantics with ordinary `Path.write_text` calls.
- Keep templates semantic and single-column. `human-readable.html.j2` reuses the ATS template structure; visual differences belong in CSS rather than duplicated document logic.

## Important Files

- `pyproject.toml`: package metadata, Python floor, dependencies, console entry point, and Hatch build configuration.
- `uv.lock`: reproducible dependency resolution; the project is recorded as an editable root package.
- `src/china_targeted_resume/__main__.py`: `python -m china_targeted_resume` entry point.
- `src/china_targeted_resume/cli.py`: argparse command surface and JSON error contract.
- `src/china_targeted_resume/pipeline.py`: end-to-end orchestration and public stage methods.
- `src/china_targeted_resume/models.py`: canonical Pydantic models and enums.
- `src/china_targeted_resume/io.py`: secure, atomic artifact I/O.
- `skills/china-targeted-resume/SKILL.md`: canonical OMP Skill trigger and orchestration instructions.
- `README.md`: supported installation, CLI, build, and troubleshooting commands.
- `schemas/request.schema.json` and `schemas/resume-document.schema.json`: principal external request and renderer boundaries.
- `tests/conftest.py`: shared synthetic-source and model-factory fixtures.
- `tests/test_end_to_end.py`: complete artifact, privacy, permission, source immutability, packaging, and real-PDF contract.

## Runtime/Tooling Preferences

- Supported Plugin runtime: Linux, OMP `>=17.3.7`, and Bun `>=1.3.0`; a complete workflow also needs the project-local locked Python environment described below.
- Supported standalone runtime: Linux with Python `>=3.14`; it does not require OMP or Bun.
- Package/environment managers are Bun for TypeScript/Plugin dependencies and `uv` for Python; keep `bun.lock` and `uv.lock` synchronized with their respective dependency changes.
- Python build backend: Hatchling (`hatchling.build`). The console script is `china-targeted-resume = china_targeted_resume.cli:main`.
- Rendering requires Playwright Chromium plus Noto Sans CJK SC or Source Han Sans SC under `/usr/share/fonts`. PDF tests use PyMuPDF.
- TypeScript runtime libraries are Ajv 2020 and `ajv-formats`; Python runtime libraries are Pydantic, Jinja2, markdown-it-py, Playwright, and PyMuPDF. Development dependencies include the OMP API package, TypeScript, Bun types, pytest, and coverage.
- The wheel explicitly includes `assets/` and the five installed IR schemas. The sdist contains the canonical Skill under `skills/china-targeted-resume/`; the curated `.skill` archive stages that canonical body and its references at archive root alongside broader schemas, scripts, and runtime source. Do not assume every repository file exists in a wheel install.
- Never commit real career data, generated run outputs, Playwright profiles/downloads, caches, `dist/`, or Skill staging artifacts; `.gitignore` lists the protected patterns.

## Testing & QA

- Plugin framework: Bun test under `tests/plugin/`. Full Plugin check: `bun run check`; focused schema/secure-I/O/source-identity check: `bun run test:kernel`.
- Python framework: pytest 8.x. Full suite: `uv run pytest -q`.
- Python tests use module-level `test_<observable_contract>` functions in `tests/test_<area>.py`; Plugin tests use Bun `test`/`describe` in `tests/plugin/*.test.ts`. No custom markers or CI workflow are defined.
- `tests/conftest.py` exposes a session-scoped read-only `synthetic_career_db`, a per-test `synthetic_db_copy`, and Pydantic model factories. Tests that mutate source fixtures must use `synthetic_db_copy` with `tmp_path`.
- Keep fixtures fully synthetic, Markdown-only, and safe for publication. Use `.invalid` domains; never add production credentials or personal data.
- Test observable boundaries: authoritative schemas, cross-language golden contracts, traversal/symlink rejection, source immutability, evidence/provenance invariants, private modes, non-overwriting output, artifact schemas, Plugin backend routing, and CLI stdout/stderr contracts.
- `tests/test_end_to_end.py` exercises actual HTML/PDF/PNG output and packaging rather than mocks. It requires Chromium, a local CJK font, and PyMuPDF, and verifies source-tree SHA-256 snapshots before/after generation.
- `coverage[toml]` is installed, but the repository defines no coverage configuration, command, or minimum threshold. Do not report or enforce an invented target.
