# Phase 3 Parity Matrix

## Scope and decision

This document records the contract evidence for Phase 3 and the boundary decision it supports. The final decision is **Option A: Plugin-first hybrid**; [`final-product-boundary.md`](final-product-boundary.md) is the normative runtime/backend description.

Phase 3 ports contracts, not guesses. TypeScript may own only deterministic behavior whose observable output and real-filesystem effects can be compared. The Python `markdown-it-py` structural validators, composition/content audit, Playwright Chromium renderer, and PyMuPDF inspector remain supported backends. There is no TypeScript heuristic that claims semantic equivalence for arbitrary paraphrases.

## How to read the evidence

The matrix uses four implementation states:

- **Ported and switched:** the Plugin tool now invokes the TypeScript implementation after parity fixtures cover the boundary.
- **Ported primitive:** TypeScript implements the deterministic contract, but a parser-backed or specialist Plugin tool remains Python by design.
- **Compared and retained:** fixtures pin the observable result, but Python remains the configured backend because a TypeScript replacement is absent or weaker.
- **External gate:** a command/path that requires a published remote and must remain open until observed. This state currently has no remaining row because the GitHub gate passed.

A command in an evidence field is an executable observation recipe, not an implied result. Record a pass only from observed command output. The final gate is 203 Python tests, TypeScript typecheck plus 98 Plugin tests, OMP `17.3.7` installed workflow evidence, and the published GitHub install/refresh evidence in `docs/migration-decision-log.md`.

## Evidence meaning preserved in product data

Migration evidence and candidate-claim evidence are separate concerns. The following candidate evidence states must remain distinct in fixtures, normalized output, reviews, and artifacts:

| State | Required proof | Blocking limitation |
| --- | --- | --- |
| **Source-verified** | The structural validator re-opened the exact source bytes and proved the source hash, span, quote, block ownership, ancestry, structural flags, and effective policy. | Does not itself authorize disclosure or a paraphrase. |
| **Mechanically transformed** | A deterministic representation-only transform preserved claim meaning and source/provenance links. | Cannot add, broaden, or infer a fact. |
| **Independently reviewed** | The required specialized agents produced separate schema-valid decisions; the decision set is retained. | Majority cannot override a hard disagreement or deterministic rejection. |
| **User-confirmed** | The user explicitly resolved the named run-local question or P2 disclosure decision. | Cannot legalize unsupported, F6, or P3 content and does not imply source verification. |

Exact locked text is the composition boundary. “Reviewed” is not “source-verified”; “user-confirmed” is not “supported”; and a mechanical transform is not an independently reviewed semantic rewrite.

## Authoritative fixtures and commands

| Evidence layer | Authority | Observable command |
| --- | --- | --- |
| Draft 2020-12 schemas | Root `schemas/*.schema.json`; TypeScript loads the five installed IR authorities through `src/kernel/schema.ts` | `bun run test:kernel` |
| Language-neutral inputs/expectations | `tests/golden/manifest.json`, `schema-cases.json`, and exact source bytes under `tests/golden/sources/` | `uv run pytest -q tests/test_golden_parity.py` and `bun test tests/plugin/golden-parity.test.ts` |
| TypeScript schema and real-filesystem kernel | `tests/plugin/kernel-schema.test.ts` and `tests/plugin/kernel-io.test.ts` | `bun run test:kernel` |
| TypeScript cross-language comparison | The same `tests/golden/` inputs and expectations consumed by the TypeScript comparator | `bun test tests/plugin/golden-parity.test.ts` |
| Tool/backend documentation contract | Registered tool names plus both final English docs and READMEs | `bun test tests/plugin/product-boundary.test.ts` |
| Plugin registration/bridge contract | Actual Extension registration and explicit Python bridge | `bun test tests/plugin/extension.test.ts tests/plugin/python-bridge.test.ts` |
| Python structural and IR contracts | Synthetic standard/nonstandard sources and parser-backed validation | `uv run pytest -q tests/test_ir_validation.py tests/test_markdown_structure_perturbations.py tests/test_phase1_nonstandard_smoke.py` |
| Python composition, audit, render, and real PDF | Synthetic end-to-end outputs, Chromium, PyMuPDF, previews, modes, and source snapshot | `uv run pytest -q tests/test_composition.py tests/test_rendering.py tests/test_end_to_end.py tests/test_resume_variants_schema.py` |
| OMP local package discovery | OMP `17.3.7`, linked checkout, invocation from outside the repository | Evidence record in `docs/migration-decision-log.md` |
| OMP remote publication | Published owner/repository and network-visible source | `omp plugin install github:OWNER/REPOSITORY`; then `omp plugin install github:OWNER/REPOSITORY --force` from a fresh external session |

The two golden commands must read the same language-neutral fixtures. A TypeScript-only expected-value file or a Python-only expected-value file is not cross-language evidence.

## Exact normalization policy

Normalization exists only to remove representation differences or values allocated during a run. It is applied after schema validation; it may not make invalid data comparable.

1. **JSON parsing and object keys.** Decode UTF-8 JSON, compare JSON value types exactly, and serialize object members in lexicographic key order for the comparison transcript. Object member order is representational and is the only general JSON reordering allowed.
2. **Arrays.** Array order is never normalized. Requirement order, evidence order, review order, provenance order, variant order, artifact lists, previews, errors, and audit findings remain exact.
3. **Runtime timestamps.** The manifest's complete allowlist is `run.started_at`, `run.finished_at`, and `artifact.generated_at`. Replace one of those values with `<TIMESTAMP>` only when it was runtime-generated and is a valid UTC timestamp. JD publication/access dates, freshness checks, expirations, and user-confirmation times are semantic inputs and remain exact.
4. **Allocated run directory.** The only allocated-name field is `run.directory_suffix`. Replace the generated timestamp/collision component of a directory matching `<company-slug>--<role-slug>--YYYYMMDDTHHMMSSffffffZ` with optional suffix `-NNN` by `<TIMESTAMP>-<SUFFIX>`; preserve the company/role slug prefix. The `normalized-run-suffix` fixture pins collision-free normalization. Output-root containment, relative paths, and non-overwrite results remain testable.
5. **Fixture workspace root.** No fixture-root path is currently allowlisted. If a future manifest declares one, replace only that exact temporary prefix with `<FIXTURE_ROOT>`. Do not normalize arbitrary absolute paths, `..`, symlink targets, or source/output containment failures.
6. **Line endings and terminal newline.** Normalize CRLF to LF for textual comparison. A fixture may declare whether one final newline is representational. Internal whitespace, Unicode, punctuation, case, list markers, and claim text remain exact.
7. **HTML projection.** Compare the parser-produced semantic token stream: landmark/section/tag order, visible text, heading levels, list structure, and link target/text. Ignore indentation-only inter-tag text and attribute serialization order. Do not reorder elements, collapse visible whitespace inside claims, remove links, ignore missing sections, or treat paraphrases as equivalent.
8. **PDF projection.** Compare exact page count, page-ordered extracted text after CRLF-to-LF conversion, link targets, and pass/fail findings. Preview dimensions and documented layout thresholds use their explicit numeric tolerances; no general float rounding, case folding, punctuation stripping, OCR substitution, or token-set comparison is allowed.
9. **Filesystem observations.** Compare modes (`0700` directories, `0600` files), symlink rejection, existence/nonexistence, hashes, atomic/non-overwrite outcome, and source snapshots exactly. These observations are never masked by path normalization.
10. **Never normalized.** Source hashes, source spans, stable IDs, claim text, policy values, review outcomes, provenance links, variant order, and artifact base names are never normalized. Neither are schema errors, domain error codes, hard-gate reasons, confirmation requirements, audit findings, or PDF acceptance results.

A new ignored field requires an explicit fixture-manifest change, a reason showing genuine nondeterminism, and review in both comparators. Wildcard key removal and recursive “drop all dates/paths/IDs” rules are prohibited.

## Phase 3 step matrix

| Step | Contract evaluated | Decision/backend | State | Fixture or focused evidence | Observable command |
| --- | --- | --- | --- | --- | --- |
| 1. Schemas and IR models | Accepted/rejected Draft 2020-12 documents, `additionalProperties: false`, formats, enums, conditionals, normalized JSON | Root schemas remain authoritative; TypeScript uses Ajv `8.17.1` plus `ajv-formats` `3.0.1`, both exact pins in `package.json` | Ported primitive | `tests/plugin/kernel-schema.test.ts`; `tests/golden/` schema accept/reject cases | `bun run test:kernel`; `uv run pytest -q tests/test_golden_parity.py`; `bun test tests/plugin/golden-parity.test.ts` |
| 2. Secure I/O | Canonical containment, source/output separation, symlink rejection, private directory/file modes, atomic non-overwrite, run allocation | `src/kernel/secure-io.ts`; Python `io.py` remains for the standalone pipeline and retained Python tools | Ported primitive | `tests/plugin/kernel-io.test.ts` uses real temporary files, symlinks, modes, a writer race, and collision allocation; Python end-to-end retains mode/source checks | `bun run test:kernel`; `uv run pytest -q tests/test_end_to_end.py tests/test_role_dossier.py` |
| 2. Source identity | SHA-256 of exact bytes, path containment, spans, quotes, source change detection | `src/kernel/source-identity.ts`; Python parser remains authoritative for Markdown block/ancestry semantics | Ported primitive; parser retained | `tests/plugin/kernel-io.test.ts`; golden hash/span cases; parser perturbations for fences, quotes, examples, and inherited policy | `bun run test:kernel`; `bun test tests/plugin/golden-parity.test.ts`; `uv run pytest -q tests/test_markdown_structure_perturbations.py tests/test_ir_validation.py` |
| 3. Effective policy | Most-restrictive F/P inheritance, domain separation, F6/P3 rejection, P2 confirmation, output-mode/variant constraints | `src/kernel/policy.ts`; Python parser supplies structurally proven inputs | Ported primitive | `tests/plugin/kernel-policy-approval-provenance.test.ts`; golden policy cases; inherited F6/P3 parser fixture | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts tests/plugin/golden-parity.test.ts`; `uv run pytest -q tests/test_policy.py tests/test_markdown_structure_perturbations.py` |
| 3. Approval and exact locking | State transitions, independent hard disagreement, P2 resolution, exact approved text, unsupported rejection, run/evidence/review/confirmation digest | `resume_lock_approved_claims` uses `src/kernel/approval.ts`; no Python alternate and no semantic-equivalence heuristic | Ported and switched | `tests/plugin/kernel-policy-approval-provenance.test.ts`; golden approval cases; reviewer hard-gate fixtures; Plugin integration contract | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts tests/plugin/golden-parity.test.ts tests/plugin/python-bridge.test.ts`; `uv run pytest -q tests/test_agent_contracts.py tests/test_ir_validation.py` |
| 3. Provenance | Every locked origin/reviewer ID resolves in the digest-bound evidence/review bodies; every visible artifact claim remains covered | `src/kernel/provenance.ts` owns lock-time closure; Python composition/audit owns final provenance artifacts and visible-output closure | Ported primitive with retained downstream check | `tests/plugin/kernel-policy-approval-provenance.test.ts`; golden provenance cases; Python visible-fact audit | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts tests/plugin/golden-parity.test.ts`; `uv run pytest -q tests/test_evidence.py tests/test_composition.py` |
| 4. Composition | Per-reader selection, exact locked text, deduplication, omission, variant order/names, underfill | Python; no TypeScript composition port | Compared and retained | Language-neutral golden variant/document expectations freeze normalized output, order, names, underfill, and partial-failure behavior; Python composition, variant-schema, and end-to-end regressions exercise the production backend. | `uv run pytest -q tests/test_golden_parity.py tests/test_composition.py tests/test_resume_variants_schema.py tests/test_end_to_end.py`; `bun test tests/plugin/golden-parity.test.ts` |
| 4. Content audit | Truthfulness, privacy, ATS structure, provenance, hard findings and warnings | Python; no TypeScript content-audit port | Compared and retained | Language-neutral golden audit expectations pin clean, unsupported/placeholder, and provenance-gap findings; Python composition/end-to-end audit regressions exercise the production backend. | `uv run pytest -q tests/test_golden_parity.py tests/test_composition.py tests/test_end_to_end.py`; `bun test tests/plugin/golden-parity.test.ts` |
| 5. Semantic HTML | One-column semantic order, headings/lists, visible text, links, local templates, CJK layout contract | Python/Jinja renderer | Retained; not a cross-language port | Golden files document the semantic projection. Production evidence renders and inspects synthetic HTML/PDF output. | `uv run pytest -q tests/test_rendering.py tests/test_end_to_end.py` |
| 5. Chromium PDF/preview | Actual render, fonts, links, page budgets, compaction, private artifacts, previews | Python Playwright Chromium | Retained; not a cross-language port | Golden files document expectations only. Production evidence uses real Chromium, files, and previews. | `uv run pytest -q tests/test_rendering.py tests/test_end_to_end.py` |
| 6. PDF inspection | Page count, extracted text/language, links, blank/overflow signals, fonts/layout, previews, deterministic errors | Python/PyMuPDF | Retained because it is stronger; not a cross-language port | Production evidence runs PyMuPDF inspection for every generated manifest variant. | `uv run pytest -q tests/test_end_to_end.py` |
| 3.3. Tool cutover | One explicit backend per tool; run-bound lock rechecked before composition; bounded private-safe errors; no silent alternate-language retry | Only `resume_lock_approved_claims` changes Plugin backend in Phase 3 | Ported and switched at one boundary | Approval kernel, Plugin integration, golden comparison, boundary matrix, and Python bridge errors | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts tests/plugin/extension.test.ts tests/plugin/golden-parity.test.ts tests/plugin/product-boundary.test.ts tests/plugin/python-bridge.test.ts` |
| 3.4. Product boundary | Plugin/CLI runtime support, specialist quality, maintenance cost, install/update reliability | Option A: Plugin-first hybrid | Final | This document, final boundary, READMEs, migration decision log | `bun test tests/plugin/product-boundary.test.ts` |

### What was deliberately not ported

- Markdown structural parsing, source-map structural validation, role-IR proof validation, and evidence-IR proof validation.
- Variant composition and content audit.
- Jinja/HTML generation, Playwright Chromium rendering, compaction, and previews.
- PyMuPDF inspection.
- The supported standalone Python CLI.

These are retained product components, not stale aliases. Their Plugin tools name Python explicitly and fail if the configured Python backend is unavailable.

## Golden contract coverage

| Observable contract | Accepted fixture | Rejected/edge fixture | Compared output |
| --- | --- | --- | --- |
| Schemas | Valid source map, role input, evidence input, review decision, approved claims, request/document/variant shapes | Missing required fields, extras, bad format/enum/conditional, wrong version | Exact validation success or stable error class/path/keyword |
| Normalized JSON | Canonical language-neutral payload | Type or order change | Exact JSON values under the normalization policy above |
| Stable identity | Unchanged bytes/path/span | Changed bytes, forged hash, moved/out-of-range span | IDs, SHA-256 hashes, byte/line spans, quotes |
| Effective policy | Eligible F1-F5/P0-P2 with required confirmation | Inherited F6/P3, policy omission, fenced/example/quote/HTML/template/secrets | Effective F/P values and stable rejection reasons |
| Approval lock | Supported extractive or independently reviewed exact claim with required user decision | Unsupported claim, hard reviewer disagreement, unknown P2, contribution/metric disagreement | Exact locked text, state, decision/reason, source/evidence IDs |
| Provenance | Every visible claim covered by eligible origins | Orphan, private, stale-dynamic, or company-as-personal claim | Coverage records and audit finding |
| Variants/artifacts | Recruiter, technical, optional extended | Wrong order/name/path, missing required variant, traversal, retained failed variant | Variant order, target/actual pages, status flags, exact artifact/previews names |
| Content audit | Truthful, private, structurally complete document | Unsupported visible text, missing provenance, privacy/ATS regression | Findings, warnings, success flag |
| Semantic HTML | Correct landmark/heading/list/link order | Missing/reordered/duplicated visible structure | Semantic token stream; no paraphrase matching |
| PDF inspection | Real readable PDF within target and expected language/layout | Too many/blank pages, missing text/link/font, overflow/preview failure | Page count, ordered extracted text, links, findings, preview observations |
| Modes/non-overwrite | New private run and atomic files | Broad permissions, source/output overlap, symlink/traversal, existing destination | `0700`/`0600`, explicit error, unchanged source snapshot, retained previous run |

## Final verification matrix

Every required scenario has a concrete fixture/test evidence path. “Retained Python” means the test is evidence for the chosen backend, not a missing migration item.

| Required scenario | Primary fixture/evidence | Boundary exercised | Expected observable result | Evidence command/record | Status |
| --- | --- | --- | --- | --- | --- |
| Known `markdown-career-v1` fast path | `tests/fixtures/synthetic-career-db/`; Tier A full-run test | Python adapter through complete pipeline | Exact current JD, direct mappings, two default variants, private artifacts, unchanged source | `uv run pytest -q tests/test_end_to_end.py` | Retained Python |
| Heterogeneous agent-assisted path | `tests/fixtures_nonstandard/nonstandard-repository/` | Source map + normalized IR + approvals | Metadata-first discovery; uncertain semantics remain pending; supported claim alone locks | `uv run pytest -q tests/test_phase1_nonstandard_smoke.py` | Parser Python; contracts compared |
| Extractive claim | Golden `extractive-mechanical` case | Source proof, policy, lock, provenance | Exact source-supported text locks with stable origins | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts tests/plugin/golden-parity.test.ts` | TypeScript lock |
| Reviewed semantic claim | Golden `reviewed-semantic-independent` case plus reviewer disagreements | Independent reviews and exact lock | Locks only schema-valid reviewed text with no hard disagreement and required proof | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts tests/plugin/golden-parity.test.ts`; `uv run pytest -q tests/test_agent_contracts.py` | TypeScript lock |
| Rejected unsupported claim | Golden `unsupported-claim` matrix case; IR validation fixtures | Evidence validation and approval | Stable rejection; absent from approved claims, composition, and provenance | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts`; `uv run pytest -q tests/test_ir_validation.py` | Python validator + TypeScript lock |
| Inherited F6/P3 rejection | Golden `inherited-f6-p3`; Markdown perturbation source | Structural ancestry and effective policy | Descendant is rejected with exact provenance even if it claims permissive local flags | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts`; `uv run pytest -q tests/test_markdown_structure_perturbations.py` | Python parser + TypeScript policy/lock |
| Fenced/example rejection | Golden `fenced-example`; Markdown perturbations | Block classification/source proof | Fence/example/template text cannot become candidate evidence | `bun test tests/plugin/golden-parity.test.ts`; `uv run pytest -q tests/test_markdown_structure_perturbations.py` | Python parser |
| P2 confirmation | Golden P2 unknown/confirmed pair | Effective disclosure and run-local user decision | Unknown blocks; explicit scoped confirmation permits eligible exact claim | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts tests/plugin/golden-parity.test.ts` | TypeScript policy/lock |
| Stale/conflicting JD | Synthetic Acme/Clockwork research and Tier B run | Target resolution, source precedence, limitations | Current exact JD wins without deleting conflict; stale/partial coverage stays explicit/null | `uv run pytest -q tests/test_role_dossier.py tests/test_end_to_end.py` | Retained Python |
| Recruiter and technical variants | Golden all-variant manifest and Tier A run | Composition, artifacts, audit/PDF | Ordered `resume-recruiter-1p` and `resume-technical-2p` families with exact names | `uv run pytest -q tests/test_golden_parity.py tests/test_end_to_end.py tests/test_resume_variants_schema.py` | Retained Python |
| Optional extended variant | Golden all-variant manifest and Tier B opt-in run | Composition, artifacts, audit/PDF | Adds ordered `technical-profile-3p` family only when requested | `uv run pytest -q tests/test_golden_parity.py tests/test_end_to_end.py tests/test_resume_variants_schema.py` | Retained Python |
| Partial variant failure retained | Golden `variants.partial-failure.manifest`; failed page-count schema test | Manifest and completion reporting | Failed variant remains with false audit/PDF status; workflow does not report complete | `uv run pytest -q tests/test_golden_parity.py tests/test_resume_variants_schema.py`; `bun test tests/plugin/golden-parity.test.ts` | Shared schema; retained Python manifest |
| `targeted_application` mode | Golden mode/policy cases | P2 eligibility and output constraints | Confirmed eligible P2 may be used; P3/F6 never used | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts`; `uv run pytest -q tests/test_policy.py` | TypeScript policy/lock + Python compose |
| `public_portfolio` mode | Golden mode/policy cases | Disclosure restriction | Application-only/private material is excluded | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts`; `uv run pytest -q tests/test_policy.py tests/test_composition.py` | TypeScript policy/lock + Python compose |
| `master_resume` mode | Golden mode and composition cases | Broader selection without target overclaim | Broader evidence remains source-backed; insufficient target is not called exact | `bun test tests/plugin/kernel-policy-approval-provenance.test.ts`; `uv run pytest -q tests/test_composition.py` | TypeScript lock + Python compose |
| Non-overwrite and private filesystem | Golden IO cases; real-filesystem kernel and Python permission assertions | Run allocation/atomic writes/modes | Distinct timestamp/collision directory; `0700` directories, `0600` files; prior run intact | `bun run test:kernel`; `uv run pytest -q tests/test_end_to_end.py tests/test_role_dossier.py` | TypeScript primitives and retained Python I/O |
| Source immutability | End-to-end SHA-256 snapshot before/after | Complete pipeline | Every source file hash is unchanged and output is outside source | `bun run test:kernel`; `uv run pytest -q tests/test_end_to_end.py` | Retained Python + shared invariant |
| Semantic HTML | Golden HTML projection and end-to-end renderer | Document-to-HTML order | Single-column sections, headings, lists, visible text, and links remain ordered | `uv run pytest -q tests/test_golden_parity.py tests/test_rendering.py tests/test_end_to_end.py` | Retained Python |
| Real PDF and preview | Real synthetic render/inspection | Chromium render plus PyMuPDF inspection | Actual page/text/link/font/layout/preview checks pass for every listed variant | `uv run pytest -q tests/test_end_to_end.py` | Retained Python/PyMuPDF |
| Local OMP install/update/discovery | Phase 2 decision-log record plus help contract tests | Local link, package discovery, `/resume-help`, `/resume-status` outside project | OMP `17.3.7` loads seven commands, ten tools, Skill, and seven agents; help is model-free | Observed install/status plus focused help smoke; see `docs/migration-decision-log.md` | Observed local baseline |
| Remote GitHub install/update | `github:ParticleG/china-targeted-resume-plugin`; installed `.bun-tag` | Installer, recorded remote source/commit, forced refresh, fresh external session | GitHub install and forced refresh complete; `/resume-status` loads outside the repository | `omp plugin install github:ParticleG/china-targeted-resume-plugin`; repeat with `--force`; see `docs/migration-decision-log.md` | Observed remote gate passed |

## Final gate interpretation

A Phase 3 acceptance record is valid only when all of the following are true:

1. both language-neutral golden consumers pass against the same fixture revision;
2. the switched tool integration and no-silent-fallback contract pass;
3. the Python structural, composition, rendering, real-PDF, privacy-mode, permission, non-overwrite, and source-immutability checks pass;
4. every required variant in `resume-variants.json` has true content-audit and PDF status before the workflow reports completion;
5. the READMEs and final boundary match the registered tool names and supported runtime floors;
6. the published GitHub install records its source/commit, forced refresh succeeds, and a fresh outside-project session loads the remote-installed Plugin.

The final boundary does not delete working Python, weaken structural validation, normalize semantic differences, or substitute a local link for remote publication evidence. Both local and GitHub installation paths are observed.
