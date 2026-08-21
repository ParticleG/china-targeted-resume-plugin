# OMP Plugin Migration Decision Log

## 2026-08-21 — Bootstrap

**Decision:** Implement the migration in the self-contained sibling project `china-targeted-resume-plugin`, cloned from source commit `76c247c`. The original `china-targeted-resume` checkout remains unchanged.

**Evidence:** The source checkout was clean; the committed resume-variant implementation is the current baseline and its test, build, and Skill-package gates passed before cloning.

**Alternatives rejected:** Depending on a sibling Python checkout would make the Plugin incomplete and non-installable. Editing the source project would violate the request to create a new project.

**Affected contracts/files:** Entire new repository; `docs/omp-plugin-migration-plan.md`.

**Verification:** The new repository has independent Git metadata and no shared hard links.

**Commit:** Pending implementation commits.

**Follow-up:** Preserve source behavior while adding Plugin-first orchestration.

## 2026-08-21 — Schema baseline

**Decision:** Treat the committed request and resume-document shapes as an intentional clean cutover that remains `schema_version: 1`. New proof-carrying IR contracts have their own independently versioned schemas and models.

**Evidence:** The baseline already uses `include_extended_profile` and the authoritative `resume-variants.json`; restoring `target_pages` would conflict with committed callers and tests.

**Alternatives rejected:** Incrementing unrelated request/document versions only because migration work begins; reintroducing caller-selected page counts.

**Affected contracts/files:** `schemas/request.schema.json`, `schemas/resume-document.schema.json`, new IR schemas, Python and TypeScript IR models.

**Verification:** Existing schema and variant tests remain part of every phase gate.

**Commit:** Pending implementation commits.

**Follow-up:** Version an IR schema only for an actual incompatible IR change.

## 2026-08-21 — Final runtime boundary

**Decision:** Target a Plugin-first hybrid. TypeScript owns OMP registration and orchestration, strict IR validation, secure I/O/source identity, and deterministic policy/approval/provenance. Python remains the supported standalone CLI and the specialist composition, Chromium rendering, and PyMuPDF inspection path unless parity evidence proves replacement is stronger.

**Evidence:** OMP 17.3.7 exposes typed Extension commands/tools but no public replacement for built-in task orchestration. The Python implementation already has audited PDF and packaging behavior.

**Alternatives rejected:** Reimplementing OMP task management; deleting Python for language uniformity; weakening PDF inspection to claim a TypeScript-only result.

**Affected contracts/files:** `package.json`, `src/plugin/`, `skills/`, `agents/`, Python package, parity fixtures.

**Verification:** Cross-language golden fixtures and final verification matrix.

**Commit:** Pending implementation commits.

**Follow-up:** Keep each switched Plugin tool explicit; no silent backend fallback.

## 2026-08-21 — Remote installation gate

**Decision:** Implement and verify local installation, package discovery, and recorded update metadata. Treat GitHub installation/update as an external publication gate until this new repository has an accessible remote.

**Evidence:** `omp plugin install github:OWNER/REPO` requires a published repository and network-visible source. Local implementation cannot fabricate a remote GitHub installation result.

**Alternatives rejected:** Claiming remote verification from a local clone; publishing without explicit repository and account authorization.

**Affected contracts/files:** Plugin documentation, package metadata, final verification report.

**Verification:** Local package/link discovery from a non-project directory; remote commands documented but not falsely reported as executed.

**Commit:** Pending implementation commits.

**Follow-up:** Run the remote gate after repository publication.

## 2026-08-21 — Phase 1 gate

**Decision:** Advance to Phase 2. Phase 1 uses parser-authoritative structural revalidation and proof-carrying IR; the known `markdown-career-v1` adapter retains only its documented fallback-policy fast path.

**Evidence:** The structural parser reparses exact bytes, proves hash/span/quote/ancestry/block ownership, inherits F/P policy, rejects fences/quotes/HTML/examples/templates/secrets, and refuses forged flags. Role/evidence approval stages require a source map and source root. Generation resolves every approved origin to verified evidence and never synthesizes provenance.

**Alternatives rejected:** Optional structural lookup; trusting submitted F1/P0 flags; fabricated paths or zero hashes; making all markerless heterogeneous content public; removing the existing adapter's deterministic source contract.

**Affected contracts/files:** `markdown_structure.py`, `markdown_career_v1.py`, `ir.py`, `validation.py`, `pipeline.py`, `cli.py`, five IR schemas, perturbation and IR tests.

**Verification:** Focused structural/evidence/policy/composition tests: 81 passed. Focused CLI/end-to-end gate: 13 passed. Full Python suite: 168 passed, including real Chromium PDF/preview, source immutability, private modes, and variant manifest checks. `uv build` produced wheel and sdist. `scripts/package_skill.py` produced `dist/china-targeted-resume-plugin.skill`.

**Commit:** Pending phase commits.

**Follow-up:** Phase 2 must preserve the six source-bound CLI stages and use OMP's built-in task runtime.

## 2026-08-21 — Phase 2 gate

**Decision:** Advance to Phase 3 for local contract migration. The Plugin uses OMP's built-in `task` orchestration through the canonical Skill; the Extension owns only typed commands/tools, privacy state, and the deterministic Python bridge.

**Evidence:** OMP 17.3.7 loaded the linked Plugin from `/tmp`, consumed `/resume-status`, and discovered the installed extension package with colocated Skill and seven agent definitions. At this phase gate the package registered six workflow commands and nine tools; the later `/resume-help` command is a deterministic UX addition and does not change the kernel boundary. Metadata-only is default; raw slices require recorded reviewed-semantic authorization and deterministic prefiltering. OMP session persistence is disclosed and audited rather than hidden.

**Alternatives rejected:** Reimplementing OMP task lifecycle; raw payloads in argv; Plugin-owned source-body state; silent claim approval; claiming Plugin install also installs the standalone CLI.

**Affected contracts/files:** `package.json`, `bun.lock`, `src/plugin/`, `skills/china-targeted-resume/`, `agents/`, Python package/schema resources, Plugin/Python tests.

**Verification:** `bun run check`: TypeScript typecheck plus 26 Plugin tests passed, including registration, privacy, malformed JSON, nonzero exits, cancellation, timeout, private temporary modes, and cleanup. Agent/IR/privacy focused tests: 15 passed. Full Python suite: 175 passed. Wheel, sdist, and `.skill` package built. `omp plugin link ... --force` installed and updated version 0.2.0; outside-project `/resume-status` completed without extension errors.

**Commit:** Pending phase commits.

**Follow-up:** GitHub install/update and a remote-source lock remain an external publication gate. Do not claim them until the new repository is published with user-authorized owner/repository credentials.

## 2026-08-21 — Phase 3 and final local gate

**Decision:** Finalize Option A, Plugin-first hybrid. TypeScript owns OMP orchestration, strict schema normalization, secure I/O/source identity primitives, deterministic policy/approval/provenance, privacy/session controls, and the same-run approval lock. Python remains the standalone CLI and the authoritative Markdown parser, composition/audit, Chromium rendering, and PyMuPDF inspection backend.

**Evidence:** Shared language-neutral fixtures execute both production kernels only for the ported boundaries: schema normalization, UTF-8 source identity, F/P policy, P2 and F3-F5 gates, independent review, exact claim locking, and lock-time provenance closure. Variant, partial-failure, audit, HTML/PDF, and retained filesystem expectations are documented in golden files but are verified by their real Python or TypeScript production suites rather than mislabeled as cross-language parity. `resume_lock_approved_claims` is the only tool switched fully to TypeScript; `resume_compose_variants` requires its same-run digest and byte-identical approval inputs before invoking Python.

**Alternatives rejected:** TypeScript semantic-equivalence heuristics; deleting stronger Python parser/PDF behavior; test-local provenance parity; lock artifacts not bound to evidence/reviews/confirmations; silent backend fallback.

**Affected contracts/files:** `src/kernel/`, `src/plugin/`, Python validation/pipeline, five IR schemas, `tests/golden/`, Python/Bun parity tests, canonical Skill, parity matrix, final product boundary, bilingual README, AGENTS.

**Verification:** Final full Python suite: 203 passed. `bun run check`: TypeScript typecheck plus 96 Plugin/kernel/privacy tests passed. Heterogeneous/golden, secure filesystem/privacy/bridge, manifest-symlink, reviewer-wrapper/auth binding, confirmation-receipt, structured composition, real Chromium PDF/preview, installed-wheel schema, and actual OMP envelope audit contracts run in these suites. Final wheel, sdist, and `.skill` archive built. The updated Plugin was linked with OMP 17.3.7; outside-project commands and the interactive workflow below executed from `/tmp`.

**Commit:** Pending repository-owner commit policy.

**Follow-up:** The repository was subsequently published and the remote install/update gate was executed; see the final entry below.

## 2026-08-22 — Installed OMP workflow and retention smoke

**Decision:** Accept the installed OMP end-to-end workflow as behaviorally exercised, while retaining explicit source-limited content-audit failure and session-storage hardening requirements. The Plugin must not call a run complete when content audit fails even if every PDF inspection passes.

**Evidence:** A real interactive OMP 17.3.7 session was launched from `/tmp` against `tests/fixtures_nonstandard/nonstandard-repository`. The first reviewed-semantic authorization attempt observed a `0644` session JSONL and failed closed. After the synthetic test session was secured to `0600`, OMP recorded the exact remote main/task model identities, four minimum slices, consumers, purposes, retention limitation, and authorization receipt.

The run used OMP's built-in `task` runtime for metadata mapping and independent evidence, contribution/metric, privacy, and requirement review. The advisor detected four missing reviewer yields after an initial artifact pass; the workflow reran those reviewers, relocked, recomposed, rendered, and reinspected from yielded canonical decisions. Final receipts:

- Source map: `sha256:8fb742190ea951fb2405c184e74105c82251f432778bfd05ad1799515d453737`
- Evidence: `sha256:8158abfc52bce8d4e24e764af1b53a89a181a55df54c717144426d2d30d7179b`
- Approval: `sha256:c0b6a51cfd472e766aad17f9383bc52285858f88004f2b6d641cd05ae120a65c`

**Affected artifacts:** `/tmp/china-targeted-resume-omp-smoke-output/company--role--20260821T181928089794Z/resume-variants.json` is authoritative. Both recruiter and technical PDFs passed document-bound PyMuPDF inspection. The technical variant was underfilled at one page. Both manifest entries retained `audit_success: false` because the deliberately narrow authorization omitted target headline, dates, application email, and enough resume-ready evidence. The run reported this as incomplete/source-limited rather than inventing facts or claiming success. A requirement-reviewer slice outside exact consumer scope was deterministically rejected and did not enter the claim lock.

**Session audit:** The production JSONL auditor parsed the actual OMP xdev `toolResult` envelopes: 8 authorized disclosed slices, 0 out-of-scope slices, 0 forbidden sentinels, matching owner, retained artifact true, deletion claimed false. The smoke also exposed OMP-created task/advisor artifacts at `0644` under an initially `0755` session directory. The Plugin now requires the session directory to be owner-only `0700` before reviewed authorization and recursively audits task/advisor JSONL/Markdown for symlinks, owners, modes, bounded parsing, receipts, scope, and forbidden content. Group/world-readable child artifacts or incomplete receipt proof fail the audit; the Plugin never chmods OMP-owned storage automatically.

**Follow-up:** OMP's default storage observed in this environment used a `0755` session directory with `0644` child artifacts. Reviewed-semantic mode now correctly refuses that tree; operators must configure or secure OMP session storage to owner-only `0700`/`0600` before authorization.

## 2026-08-22 — GitHub publication and remote update gate

**Decision:** Publish the self-contained Plugin as the public repository `ParticleG/china-targeted-resume-plugin` after explicit user authorization.

**Evidence:** GitHub repository creation and the initial push of commit `5a2f71e` succeeded. `omp plugin install github:ParticleG/china-targeted-resume-plugin` installed version `0.2.0` into the user Plugin directory. The installed `.bun-tag` records `ParticleG-china-targeted-resume-plugin-5a2f71e`, binding the installed package to the remote owner, repository, and commit. Re-running the same GitHub install with `--force` completed the documented remote update path. From `/tmp`, a fresh noninteractive OMP 17.3.7 session consumed `/resume-status` from the remote-installed Plugin.

**Verification:** Remote URL: `https://github.com/ParticleG/china-targeted-resume-plugin`. The Plugin package exposes the Extension, canonical Skill, seven agents, Python project, schemas, and deterministic kernels without recursive Skill links. Plugin installation remains distinct from global Python CLI installation.

**Follow-up:** Re-run the GitHub install with `--force` after future published commits; marketplace-only `omp plugin upgrade` is not the update path for this direct Git source.

## 2026-08-22 — Plugin help and operator guide

**Decision:** Add `/resume-help [topic]` as a seventh, deterministic Extension command and support `help`, `-h`, and `--help` before every existing command's domain argument parser.

**Evidence:** OMP `17.3.7` does not generate per-command usage from Extension command descriptions. The new help contract uses a closed topic allowlist, prefix completions, and `ctx.ui.notify`; it never sends a model message, reads source data, mutates run state, or interprets help flags as paths/run IDs. Detailed, mirrored Plugin quickstarts, command examples, receipt flow, privacy authorization, tool inventory, artifact handling, and troubleshooting are documented in both READMEs.

**Compatibility:** Multiline help is an interactive TUI feature. OMP print mode uses a no-op Extension UI and ACP/RPC visibility depends on the client, so documentation remains the authoritative headless reference.
