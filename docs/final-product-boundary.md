# Final Product Boundary

## Decision

Phase 3 selects **Option A: Plugin-first hybrid**.

The product has two supported, separately installed entry surfaces:

1. **OMP Plugin:** TypeScript owns OMP registration, commands, privacy state, typed tool envelopes, schema-backed deterministic kernel primitives, secure filesystem/source-identity primitives, policy/approval, exact claim locks, and lock-time provenance closure. Explicit Python-backed tools retain parser-backed source validation, role/evidence validation, composition, final provenance artifacts and content audit, HTML/Chromium rendering, and PyMuPDF inspection.
2. **Standalone CLI:** the Python `china-targeted-resume` CLI remains supported for non-OMP and automated use. It does not require OMP or Bun and retains the complete deterministic pipeline.

This is a product boundary, not a temporary fallback arrangement. Each Plugin tool has one documented backend. The Plugin does not try another implementation when that backend is unavailable; it fails with a bounded, actionable error. Installing one surface does not install the other.

## Why Option A is the final choice

- **Contract parity, not language uniformity, controls migration.** Draft 2020-12 schema validation, secure filesystem/source identity, deterministic effective-policy handling, approval transitions, exact claim locking, and lock-time provenance closure can be compared without inventing meaning, so those primitives are suitable TypeScript boundaries. Final visible-artifact provenance remains independently checked by Python composition/audit.
- **The structural validators are parser-backed.** Source-map, role-IR, and evidence-IR validation re-open exact source bytes and use the Python `markdown-it-py` structural parser to prove hashes, spans, block ownership, ancestry, fences/examples, and effective policy. Replacing that with a TypeScript semantic-equivalence guess would weaken the trust boundary.
- **Composition and audit are already behavior-rich.** Variant selection, omission rules, global visible-claim deduplication, provenance, underfill handling, and audit findings remain in Python after direct production-regression evaluation. They are intentionally not labeled as TypeScript cross-language parity boundaries; a rewrite would add a second policy surface without a demonstrated user benefit.
- **Rendering is an audited specialist path.** The Python renderer preserves semantic single-column HTML order, CJK typography, links, page budgets, private artifacts, and semantic compaction before Playwright Chromium produces PDFs and previews.
- **PyMuPDF remains the stronger inspection boundary.** The retained inspector checks the real PDF's page count, extracted text and language, links, blank/overflow signals, font/layout properties, and preview images. No TypeScript library demonstrated equal observable coverage.
- **Standalone automation remains useful.** Removing Python would delete a working non-OMP CLI or require an otherwise unnecessary CLI rewrite.
- **The two-runtime cost is explicit and bounded.** Full Plugin generation still requires its project-local locked Python environment, but no global Python CLI installation. Backend ownership is listed below and unavailability never triggers a silent fallback.

## Supported runtime matrix

| Surface or operation | Supported runtime | Not implied |
| --- | --- | --- |
| OMP Plugin registration, commands, TypeScript-owned tools | Linux; OMP `>=17.3.7`; Bun `>=1.3.0` | Does not install or expose a global `china-targeted-resume` command. |
| Complete OMP Plugin workflow | Plugin requirements above; `uv`; Python `>=3.14`; locked project dependencies | Plugin installation does not run `uv sync`, install Chromium, or install fonts. |
| Plugin composition, render, and inspection | Complete Plugin workflow; Playwright Chromium; Noto Sans CJK SC or Source Han Sans SC under `/usr/share/fonts` | A generated file is not accepted merely because it exists. |
| Standalone Python CLI | Linux; `uv`; Python `>=3.14`; Chromium and a supported CJK font for render/PDF operations | Does not require OMP or Bun and does not register the Plugin. |
| TypeScript development and contract verification | Bun `>=1.3.0`; dependencies pinned by `package.json`/`bun.lock` | Does not replace the Python end-to-end and real-PDF gates. |

OMP `17.3.7` is the compatibility floor and the source-checked/local-smoke baseline. A newer OMP version is supported only while its public Extension contracts remain compatible; re-run Plugin registration and outside-project discovery checks when raising the floor.

## Per-tool backend matrix

“TypeScript” and “Python” below name the configured execution backend. A TypeScript approval-lock or manifest/path guard in front of a Python specialist does not make the specialist a TypeScript implementation.

| Plugin tool | Configured backend | Boundary and failure behavior |
| --- | --- | --- |
| `resume_discover_structure` | Python | The `markdown-it-py` structural parser builds metadata-only source maps. Missing Python/locked dependencies is an explicit bridge error. |
| `resume_read_source_slice` | TypeScript | Run-local reviewed-semantic authorization plus path, category, contact, credential, F6/P3, size, and exact-slice prefiltering. Denial fails closed; it never invokes Python as an alternative. |
| `resume_validate_source_map` | Python | Re-opens source bytes and validates identity, hashes, spans, quotes, ancestry, structural flags, and inherited policy. No TypeScript semantic substitute. |
| `resume_validate_role_ir` | Python | Parser-backed role/JD proof validation, freshness, and company/role/roadmap separation. No TypeScript semantic substitute. |
| `resume_validate_evidence_ir` | Python | Parser-backed evidence proof, support, contribution, metrics, uncertainty, disclosure, and provenance validation. No TypeScript semantic substitute. |
| `resume_lock_approved_claims` | TypeScript | Draft 2020-12 validation plus deterministic policy, hard-disagreement, user-confirmation, exact-text locking, and digest-bound provenance closure. This is the only Phase 3 Plugin-tool cutover. |
| `resume_compose_variants` | Python behind a TypeScript approval-lock guard | Recomputes and verifies the run-bound TypeScript lock before the Python backend composes recruiter, technical, and optional extended variants, writes the manifest, and runs content audit. A missing/mismatched lock or unavailable Python backend stops the tool. |
| `resume_render_variants` | Python behind a TypeScript manifest/path guard | Python/Jinja composition output and Playwright Chromium produce HTML, PDFs, and previews for every manifest-listed variant. Missing renderer prerequisites stop the tool. |
| `resume_inspect_variants` | Python/PyMuPDF behind a TypeScript manifest/path guard | Inspects every manifest-listed PDF; a subset cannot be silently accepted. Missing PyMuPDF or a failed check stops acceptance. |

The six slash commands remain TypeScript OMP orchestration entry points:

- `/resume-init` and `/resume-status` manage/report Plugin run metadata and privacy state;
- `/resume-discover`, `/resume-analyze`, `/resume-generate`, and `/resume-audit` seed the canonical Skill workflow, which uses OMP's built-in `task` runtime and the typed tools above.

Commands do not duplicate policy logic and do not form a second kernel.

## Trust labels preserved end to end

These labels are not synonyms and may not be collapsed during normalization or presentation:

| Label | What it proves | What it does not prove |
| --- | --- | --- |
| **Source-verified** | Exact current source bytes, hash, span, quote, block ownership, ancestry, and policy were structurally revalidated. | It does not authorize disclosure or establish that a transformed sentence preserves meaning. |
| **Mechanically transformed** | A deterministic operation changed representation without adding semantic content; source links remain intact. | It is not independent review and cannot justify an arbitrary paraphrase. |
| **Independently reviewed** | The required specialized reviewers emitted separate schema-valid decisions; hard disagreement remains blocking. | Reviewer majority cannot override unsupported evidence, F6/P3, contribution/metric disagreement, or a required user decision. |
| **User-confirmed** | The user explicitly resolved a confirmation-required fact or P2 disclosure for the current run and scope. | It does not make an unsupported claim source-verified or authorize P3/F6 content. |

Only exact locked claim text that satisfies the applicable combination of these states may reach composition. TypeScript contains no deterministic “semantic equivalence” heuristic for arbitrary paraphrases.

## Installation and update boundaries

### Local development or unpublished checkout

Link the absolute checkout path with OMP's local Plugin path:

```text
omp plugin link /absolute/path/to/china-targeted-resume-plugin --force
```

A local link follows that checkout. Re-linking with `--force` refreshes recorded package metadata after a version change. Provision the locked Python environment separately before using Python-backed tools. Run OMP from a directory outside the checkout when checking discovery so repository-local discovery cannot hide a packaging defect.

### Published GitHub source

Install it and explicitly refresh the same remote source with:

```text
omp plugin install github:ParticleG/china-targeted-resume-plugin
omp plugin install github:ParticleG/china-targeted-resume-plugin --force
```

The OMP `17.3.7` gate is observed: direct GitHub install succeeded, `.bun-tag` recorded `ParticleG-china-targeted-resume-plugin-5a2f71e`, forced refresh succeeded, and a fresh `/resume-status` session loaded the remote-installed Plugin from `/tmp`. Direct Git updates use the repeated install command; marketplace-only `omp plugin upgrade` is not this package's update path.

### Standalone CLI

The standalone installation/update path is the Python package environment (`uv sync` for a checkout, or an independently managed package installation). It is separate from OMP's Plugin registry. Plugin installation does not run Python dependency or browser provisioning, and Python installation does not link/update the Plugin.

## Backend-unavailable behavior

There is no backend preference flag, compatibility alias, automatic retry into a second language, or catch-all fallback. Tool registration chooses the boundary shown in the matrix:

- a TypeScript contract error returns a bounded Plugin tool error and performs no Python retry;
- a Python bridge startup, timeout, cancellation, dependency, schema, or domain error returns a structured failure and performs no TypeScript retry;
- composition, rendering, and inspection failures remain visible in `resume-variants.json`; the workflow must not report completion while any required variant audit/PDF check is false;
- source and output paths are never relaxed to recover from an error.

The standalone Python CLI remains a separate supported surface, not a fallback secretly invoked after a TypeScript tool failure except where the matrix explicitly defines that tool's Python backend.

## Verification and publication status

The language-neutral fixture contract, normalization rules, Phase 3 step evidence, and complete scenario matrix are in [`parity-matrix.md`](parity-matrix.md). The migration history is in [`migration-decision-log.md`](migration-decision-log.md).

Evidence is reported at its actual level:

- Phase 2 baseline: 175 Python tests and 26 Plugin tests passed; OMP `17.3.7` loaded the linked Plugin outside the project and `/resume-status` completed without extension errors.
- Phase 3 port/switch evidence: exact fixture and focused verification commands are named in the parity matrix; results must be recorded only from their observed output.
- Remote GitHub installation/update: external and unverified until publication.

## Clean cutover rules

- The authoritative schemas remain the root `schemas/*.schema.json` Draft 2020-12 files; TypeScript consumes them rather than maintaining a divergent schema copy.
- `resume_lock_approved_claims` names the switched Plugin boundary. Documentation must not advertise the former Python bridge route as its Plugin backend.
- Parser-backed validation, composition/audit, rendering, and PDF inspection remain intentionally supported Python code; they are not deprecated aliases.
- The canonical command and tool names in this document are the only supported Plugin names. Migration-only aliases and implicit backend selectors are not part of the product.
- Working Python code remains because it is inside the chosen product boundary, not because deletion was deferred without a decision.
