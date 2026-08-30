---
name: china-targeted-resume
description: Use this Skill whenever a user wants to turn a personal career knowledge base into an evidence-grounded master resume, public portfolio resume, or resume for a target company and role, even if they only mention choosing a company, an exact role, a JD, job fit, role research, refreshing stale role or evidence analysis, or handing confirmed gaps to a roadmap Skill. It discovers the source, builds or refreshes the seven-file role dossier, applies China recruiting context and strict evidence/privacy gates, generates and audits master/targeted/ATS resumes, and validates a local PDF. Trigger aggressively for candidate-side personal career evidence and resume or target-role work. Require an explicit request before roadmap handoff. Do not use for generic PDF conversion, recruiter-side candidate screening, or generic learning/onboarding/interest plans.
---

# China Targeted Resume

The repository README contains human-facing installation, CLI tutorials, output discovery, and troubleshooting. Do not assume it is colocated with this file after Plugin or `.skill` installation.

Use the OMP Plugin as the primary interactive surface when it is installed; otherwise orchestrate the standalone deterministic `china-targeted-resume` CLI. Language reasoning is limited to semantic mapping, independent review, requirement interpretation, and resume composition. The personal career knowledge base remains the source of truth; generated resume text never writes back to `personal-data/`.

## Non-negotiable boundaries

- Treat the configured career repository as read-only runtime input unless the user explicitly confirms a proposed seven-file role-dossier write. Never copy it into this Skill.
- Write generated artifacts outside the source root. Directories containing personal data use mode `0700`; files use `0600`.
- Persist navigation metadata only in CLI indexes and Plugin-owned state, logs, telemetry, caches, and explicit session entries. Never place contacts, credentials, derived claims, F6/P3 material, secrets, or unauthorized source bodies there. In reviewed-semantic mode, OMP-owned private session JSONL may retain the exact authorized slices sent through built-in tasks or tools; disclose and audit that retention instead of claiming it is absent or deleted.
- Never place raw private source text in slash-command arguments or child-process argv. Plugin tools pass typed JSON through private temporary input or stdin and keep only paths, IDs, and bounded non-sensitive options in argument arrays.
- Use only these role match values: `已有直接证据`, `可迁移经验`, `有知识无实践`, `明确缺口`, `待确认`.
- Keep capability match, real-world application constraints, and gap severity independent. Constraints use only `satisfied`, `unsatisfied`, `unknown`, `not_applicable`; severity uses only `Critical`, `Major`, `Minor`, or null.
- Do not invent facts, upgrade contribution verbs, broaden metric scope, turn company research into candidate experience, or treat a plan as evidence.
- For experienced-hire output, positive framing may select the strongest evidence-supported verb and foreground role relevance, but it must not exceed the owning fact. Requirement duration is authoritative only when parsed from one atomic numeric verbatim quote/span. Candidate duration is authoritative only when rebuilt from a current `EvidenceRecord` whose owning path/hash/span and extractive atomic safe claim contain the duration plus `checked_at`. A binding must exactly match both sides and every selected evidence fact before a shortfall of at most 25% may become `apply_with_risks`; arbitrary IDs, self-reported numbers, altered thresholds, compound/free-text durations, or unaudited evidence fail closed.
- Core deterministic CLI operations must run without an LLM. Do not replace CLI validation with prose review.
- A requested `zh-CN` resume must contain concise Chinese prose, not merely `locale: zh-CN`. When source claims are in another language, translate only the run-local visible `ResumeDocument` strings, preserve every `claim_id`, provenance reference, contribution verb, metric qualifier, name, and conventional technology term, then rerun content/PDF validation. Translation never changes evidence or match state.
- Roadmap creation is outside this Skill. Export a handoff only after an explicit request; never silently invoke a learning-plan Skill.

## Runtime surfaces and prerequisites

Treat the Plugin and Python CLI as separately installed surfaces:

- **OMP Plugin:** requires OMP `17.3.7` or newer, Bun `1.3.0` or newer, the installed Plugin package, `uv`, and Python `3.14` or newer. The bridge runs the bundled checkout with `uv run --project PLUGIN_ROOT --offline --frozen`; provision the locked Python dependencies beforehand, plus Playwright Chromium and a supported CJK font before rendering. Plugin installation registers the Skill, commands, tools, and agents but does **not** install a global `china-targeted-resume` executable.
- **Standalone Python CLI:** requires Python `3.14` or newer with this package and its dependencies installed, Playwright Chromium, and Noto Sans CJK SC or Source Han Sans SC for PDF output. It does not require OMP, the Plugin, or model access.

When the Plugin is available, use `/resume-init`, `/resume-discover`, `/resume-analyze`, `/resume-generate`, `/resume-audit`, and `/resume-status` as user-facing entry points. Commands collect intent and show state; they never replace deterministic policy or validation. When it is unavailable, use the CLI commands below.

## Start here

1. Identify the source root, requested output mode, target company/role, JD source, whether the optional extended profile is wanted, template, and output root. The recruiter one-page and technical two-page variants are always generated.
2. Read [source-adapter.md](references/source-adapter.md) and [privacy-policy.md](references/privacy-policy.md) before discovering or searching a career repository.
3. Default every Plugin run to **metadata-only** mode. Do not infer reviewed-semantic permission from an earlier run, Plugin installation, a broad request to “use my files,” or CLI source access.
4. If the target is ambiguous, list the available companies and roles, present the choices, and stop for selection. Never silently pick among multiple candidates.
5. Read [role-resolution.md](references/role-resolution.md), resolve Tier A-D, and record the exact `target_basis`.
6. In Plugin mode, follow the task orchestration and exposure rules below. In CLI mode, run the matching deterministic operation directly.
7. Ask only high-value confirmation questions, then continue with approved material or omit unresolved claims.
8. Treat `resume-variants.json` as the authoritative artifact-discovery manifest. Deterministically validate content and inspect every manifest-listed PDF before reporting success.

## Plugin model-exposure modes

### Metadata-only mode (default)

Models may receive only paths or opaque document IDs, hashes, source spans, headings, ancestry, block kinds, policy enums, stable IDs, run-state summaries, deterministic validation findings, and confirmation questions. Do not send source bodies or exact private slices to the main model or any task. Limit results to deterministic extractive behavior and questions when structure cannot resolve semantics.

### Reviewed-semantic mode (explicit per-run authorization)

Use this mode only when structural metadata cannot resolve material semantics. Before reading or sending any source slice, show the user and record all of the following for the current run:

1. selected model and provider, and whether processing is local or remote;
2. each disclosure category and the exact minimum slice proposed for that category, identified by document ID/path, heading/span, and purpose;
3. that OMP task prompts, tool results, and subagent results are stored in private OMP session JSONL;
4. the observed JSONL location and file permissions;
5. the configured retention/cleanup policy, including any limit on reliable or guaranteed deletion; and
6. that contacts, credentials, secrets, and all F6/P3 content remain forbidden regardless of authorization.

Require an explicit authorization response for that disclosure record and that run. Authorization is not transferable to another run, provider, category, document, consumer, purpose, or wider span. Deterministically prefilter first, then use `resume_read_source_slice` one approved span at a time and send only the smallest text needed for the named review. Never send a whole file or repository when a heading, paragraph, or claim span suffices.

For every reviewed-semantic built-in task, include the complete **actual** `SourceSliceAllowed` receipt returned for that task's slice—not a reconstructed summary—alongside the minimum content. Preserve `ok: true`, `authorizationId`, `provider`, `model`, `locality`, `mode`, `consumer`, `purpose`, `path`, `startLine`/`endLine` when present, `category` when present, `bytes`, and `requestId` when emitted. The consumer and provider/model/locality must match the task. Require the task output wrapper's `authorization_id` to copy the receipt's `authorizationId` exactly; do not add an authorization field to the closed nested decision schema. A missing, altered, fabricated, mismatched, or denied receipt rejects the task result.

Keep Plugin-owned state, logs, telemetry, caches, and explicit session entries metadata-only. Authorized slices that enter OMP-owned JSONL are private retained data: report their location, permissions, scope, and applicable retention outcome. Attempt cleanup only when the recorded policy and supported OMP APIs permit it, verify the result, and never claim deletion when it cannot be demonstrated.

## Plugin task orchestration

Use OMP's built-in `task` tool for agent work. There is no public `spawnTask`/`createSubagent` orchestration API, and `ctx.invokeTool` is not a general task bridge; do not emulate or replace OMP's task manager in the Plugin.

Every agent receives a narrow typed input and must return its declared structured result. Free-form rationale may accompany the result but cannot replace required fields. Agents never modify source data, validated IR, approval state, or locked claims directly.

1. Run `resume_discover_structure` to obtain structural metadata.
2. In one built-in `task` fanout, run `source-mapper` and `role-analyst` independently whenever their inputs do not depend on each other. The source mapper receives source structure; the role analyst receives role/JD/company structure and no candidate profile. In metadata-only mode neither receives source bodies.
3. Call `resume_validate_source_map` once and retain its `source_map_receipt.digest`. Pass that same-run digest as `sourceMapDigest` to `resume_validate_evidence_ir`; never resend a caller-supplied source map. Validate role IR through `resume_validate_role_ir`. A failed deterministic validation returns to mapping/analysis and never becomes approvable.
4. Once candidate requirements and claims exist, use another built-in `task` fanout for independent review:
   - `requirement-reviewer` checks whether each requirement is explicit, inferred, conflicted, fresh enough, and eligible for any hard gate;
   - `evidence-reviewer` checks one requirement, one proposed claim, deterministic findings, and—only when authorized—the exact supporting slices;
   - `contribution-reviewer` independently checks personal-versus-team attribution, contribution verbs, metric scope, precision, and qualifiers from only the needed evidence;
   - `privacy-reviewer` checks disclosure eligibility and redaction from policy metadata plus, only when authorized, one deterministically prefiltered slice. It does not judge job fit.
5. Keep reviewers independent: do not provide another agent's hidden reasoning, let a proposer review its own claim, or let reviewer prose overwrite IR. Aggregate typed wrappers keyed by stable IDs.
   In reviewed-semantic mode, pass each complete claim-review task wrapper—`evidence-reviewer`, `contribution-reviewer`, and `privacy-reviewer`—unchanged to `resume_lock_approved_claims`. Do not flatten, rewrite, or extract `.decision` in the main model: the lock requires wrapper `mode: reviewed_semantic`, same-run `authorization_id`, the exact `agent_role` → nested `review_kind` pairing, and the byte-identical `approved_safe_claim` binding for every approval before it flattens internally. Missing or different bindings fail closed.
   Route complete `requirement-reviewer` wrappers separately to final role-IR validation. Requirement reviews never enter a claim lock. In metadata-only mode, the only accepted canonical review bundle is exactly `{"schema_version": 1, "decisions": []}`; the lock rejects every caller-supplied nonempty raw canonical decision list.
6. Run `resume-advisor` as a watchdog over IDs and workflow summaries. It may flag missing reviewers, unresolved disagreement, absent validation, unconfirmed P2 use, unlocked claims, or missing PDF checks. It receives no raw private source body and can neither approve/reject a claim nor waive, edit, or replace deterministic validation.

### Disagreement hard gates

- Any `requirement-reviewer` finding of an unsupported requirement rejects that requirement proposal. A misclassified inference may proceed only after it is explicitly labeled and re-reviewed; reviewer votes cannot promote it to an explicit requirement.
- Any `evidence-reviewer` finding of unsupported evidence rejects the claim until new evidence is reviewed or the claim is removed.
- Any `privacy-reviewer` finding of P3 or forbidden F6 material rejects the claim. Contacts, credentials, and secrets are rejected before model exposure.
- P2 with unknown or mismatched scope stops locking. P2 is valid only for `targeted_application`, audience `recruiter` or `hiring_team`, and purpose literal `targeted_application`; public/master use rejects.
- Contribution-verb or metric-scope/precision disagreement stops locking until the user confirms the supported boundary or the claim is reduced to wording that is directly extractive from accepted evidence and then re-reviewed.
- A requirement disputed as inferred, stale, or conflicted cannot act as an explicit hard requirement. Preserve the conflict and route a material application decision to the user.
- Missing, malformed, or non-independent reviewer output is not an approval. Reviewer majority and advisor silence never override a hard rejection, missing authorization, or deterministic validator failure.

## Validate, lock, and produce

After review aggregation, proceed in this order without shortcuts:

1. Run `resume_validate_evidence_ir` with the validated `sourceMapDigest` and only its accepted metadata-only selector or authorized canonical evidence payload. Retain the returned `evidence_receipt.digest`; the validated source map and evidence bundle remain private in the Plugin runtime.
2. Resolve hard gates and material disagreements with the user; revalidate any changed IR and use the new evidence receipt.
3. Call `resume_lock_approved_claims` with `evidenceReceiptDigest` set to that same-run evidence receipt. In reviewed-semantic mode its payload contains the full unchanged claim-review wrappers, byte-identical `approved_safe_claims`, and one explicit canonical `output_mode` (or matching `request.output_mode`); in metadata-only mode use only the empty canonical review bundle above. Never flatten wrappers in the caller, pass requirement-review wrappers, send a nonempty raw canonical decision list, resend evidence/source-map bodies, or supply caller-authored `user_confirmations` or confirmation receipts. The lock checks each wrapper's reviewed mode, same-run authorization, role/review-kind pair, and exact claim binding before extracting its nested `ReviewDecisionIR`. When confirmation is required, the tool derives a metadata-only, exact-claim-digest `ConfirmationRequest`, shows the byte-identical claim transiently through `ctx.ui.confirm`, and mints a same-run `ConfirmationReceipt` bound to the interactive user, timestamp, nonce, evidence ID, audience, purpose, and `targeted_application` mode. Retain the returned `approvalReceiptDigest`; do not persist raw claims in Plugin session state.
4. Call `resume_compose_variants` with only the same-run `evidenceReceiptDigest`, the returned `approvalReceiptDigest`, output paths/options, and generation-only metadata whose output mode matches the lock. Never send `approval_lock`, evidence, reviews, approved claims, or confirmation bodies. The tool resolves the private bundles, revalidates receipts, recomputes approval and the digest, then invokes Python composition. It rejects missing, stale, cross-run, output-mode-mismatched, or payload-mismatched receipts.
5. Read the resulting `resume-variants.json`; do not infer variants from filenames. Run `resume_render_variants`, then `resume_inspect_variants`, for exactly the manifest-listed variants.
6. Require each listed variant's content validation, provenance/audit, PDF page contract, extracted-text checks, and privacy checks to pass independently. The advisor may report missing stages but cannot turn a failure into success.

## Stop or confirm

Stop and ask the user when:

- more than one company or role matches;
- Tier D lacks a company or meaningful role direction, unless the user explicitly requests a master resume;
- persisting a dossier into the source repository is requested but the proposed seven files have not been reviewed and confirmed;
- an output path would be inside the source root, escape an allowed root, overwrite an existing run, or expose personal data through weak permissions;
- a P2 claim might be used without a confirmed `targeted_application` audience and purpose;
- a hard application constraint is `unknown` and materially affects the application decision;
- a dynamic fact, contribution boundary, metric scope, or selected high-value claim cannot be verified.

Do not stop Tier B merely because a complete current JD is unavailable. Ask at most six questions per round, ordered by impact: current employment facts; personal versus team contribution; metric source/scope/precision; dates; P2 permission; stale public evidence. Omit unresolved claims rather than rendering placeholders.

## Resource selection

Read references progressively, not all at once:

| Need | Read |
| --- | --- |
| Discover, index, or retrieve personal evidence | [source-adapter.md](references/source-adapter.md), [privacy-policy.md](references/privacy-policy.md) |
| Resolve exact JD, exact role, role family, or insufficient target | [role-resolution.md](references/role-resolution.md) |
| Analyze or persist a role dossier | [role-dossier-contract.md](references/role-dossier-contract.md), [requirement-analysis.md](references/requirement-analysis.md), [competency-model.md](references/competency-model.md) |
| Map evidence and decide whether a claim may appear | [evidence-policy.md](references/evidence-policy.md) |
| Model gaps, constraints, or application recommendation | [gap-analysis.md](references/gap-analysis.md) |
| Apply China-market and experienced-hire wording | [china-recruiting-context.md](references/china-recruiting-context.md), [social-hire-writing.md](references/social-hire-writing.md) |
| Learn from public resume patterns without copying claims | [public-resume-patterns.md](references/public-resume-patterns.md) |
| Compose outputs, audit, render, or inspect PDF | [output-contract.md](references/output-contract.md), [resume-audit.md](references/resume-audit.md), [privacy-policy.md](references/privacy-policy.md) |
| Export confirmed gaps for another Skill | [roadmap-handoff.md](references/roadmap-handoff.md) |

## Commands

Discover local choices:

```bash
china-targeted-resume list-companies --source SOURCE_ROOT
china-targeted-resume list-roles --source SOURCE_ROOT --company COMPANY
```

Generate for an exact role, optionally supplying exactly one JD input:

```bash
china-targeted-resume generate \
  --source SOURCE_ROOT \
  --company COMPANY \
  --role ROLE \
  [--jd-text JD_TEXT | --jd-file JD_FILE | --jd-url JD_URL] \
  [--experience-duration-diagnostics-file DURATION_DIAGNOSTICS_JSON] \
  --mode targeted_application \
  [--include-extended-profile] \
  --template adaptive \
  --output OUTPUT_ROOT
```

The default output is `resume-recruiter-1p` plus `resume-technical-2p`. Add `--include-extended-profile` only when the user wants the opt-in `technical-profile-3p`. Add `--export-roadmap-handoff` only when the user explicitly asks for that handoff; prefer the separate export command after gaps have been reviewed.

Without OMP, use `guided-generate` to select a discovered company and role interactively. Prompts use a dedicated terminal device, success stays machine-readable JSON on stdout, and expected errors remain a single JSON object on stderr. Non-interactive callers must pass exact `--company` and `--role` values.

```bash
china-targeted-resume guided-generate \
  --source SOURCE_ROOT_OR_COMPANY_RESEARCH \
  [--jd-file JD_FILE] \
  [--experience-duration-diagnostics-file DURATION_DIAGNOSTICS_JSON] \
  --output OUTPUT_ROOT
```

The `adaptive` strategy keeps every document semantic and single-column: the recruiter one-page variant uses `ats-simple`, while the technical two-page and optional extended three-page variants use `human-readable`. Each manifest entry records the concrete template.

Duration diagnostics require a baseline run first. Read its deterministic `requirements.json`, `evidence-map.json`, and private `experience-duration-facts.json`, then create a binding using the exact explicit requirement ID and an evidence ID from that fact index. Before binding, the rerun reopens each owning source span and rebuilds the record; candidate scope/years/check time must again match, while the required scope/minimum/maximum must match the requirement quote/span. Any mismatch fails before recommendation.

Analyze and refresh:

```bash
china-targeted-resume analyze-role --request REQUEST_JSON
china-targeted-resume refresh-role --role ROLE_DOSSIER
china-targeted-resume refresh-match --role ROLE_DOSSIER
```

Export a handoff:

```bash
china-targeted-resume export-roadmap-handoff \
  --role ROLE_DOSSIER \
  --severity Critical,Major \
  --output RUN_DIR/roadmap-handoff.json
```

Run deterministic stages directly when diagnosing or completing a run:

```bash
china-targeted-resume build-evidence-map --run RUN_DIR
china-targeted-resume validate-content --run RUN_DIR
china-targeted-resume render --document RUN_DIR/resume-technical-2p.document.json --output RUN_DIR/resume-technical-2p.pdf
china-targeted-resume inspect-pdf --pdf RUN_DIR/resume-recruiter-1p.pdf --max-pages 1
china-targeted-resume inspect-pdf --pdf RUN_DIR/resume-technical-2p.pdf --max-pages 2
china-targeted-resume inspect-pdf --pdf RUN_DIR/technical-profile-3p.pdf --max-pages 3
```

Discover generated variants from `RUN_DIR/resume-variants.json`; do not infer their presence from filenames. Render or inspect the three-page artifact only when its manifest entry exists. Each variant's `.validation.json`, `.audit.md`, provenance, and PDF result must pass independently.

## Workflow: exact JD

1. Resolve Tier A only when company, exact role, and a complete current JD are all available.
2. Read the dossier, requirement, competency, evidence, gap, output, audit, and privacy references.
3. Preserve explicit JD quotes and source spans; keep inferences separate.
4. Build the complete requirement-to-evidence matrix and report explicit coverage with its calculation.
5. Confirm selected P2 material and uncertain high-impact claims.
6. If the requested output language differs from selected source prose, translate only the run-local visible strings under the rule above; never translate by strengthening or summarizing a claim.
7. Generate both default variants and the optional extended variant when requested; validate, render, and inspect each one against its manifest page contract. Treat a successful sparse `underfilled` variant as an explicit limitation rather than padding it to the target. Confirm the requested language is actually present in extracted PDF text. A PDF file existing is not success; every acceptance check must pass.

## Workflow: role only

1. Resolve an exact role with partial, old, company-level, or absent JD evidence as Tier B.
2. Use the exact role identity plus dated company recruiting, technology, business, and archived role sources.
3. Continue generation; set `explicit_requirement_coverage` and `coverage_calculation` to null.
4. Mark missing requirements, source age, conflicts, inference emphasis, and limitations in audit artifacts, not visible resume prose.
5. Keep inferred requirements out of hard gates.
6. Generate the default recruiter and technical variants, add the extended profile only when requested, and validate every generated variant independently.

For Tier C, prefer exact-role choices when available; otherwise create a clearly labeled company/role-family draft only on request, with lower confidence and no role-level coverage claim. For Tier D, list choices and do not emit a misleading match score.

## Workflow: analyze role

1. Normalize the request and run `analyze-role`.
2. Create a run-local dossier by default. Persist to `role-research/<company-role-slug>/` only after explicit confirmation.
3. Enforce the seven owning boundaries in [role-dossier-contract.md](references/role-dossier-contract.md).
4. Model explicit requirements, inferences, competencies, constraints, evidence states, gaps, and interview preparation separately.
5. Treat a numeric score as an explicitly requested, fully disclosed heuristic—not an employment probability.

## Workflow: refresh

- Use `refresh-role` when a JD or company source changes. Compare source hashes and update only affected requirements, competencies, mappings, gaps, and interview questions; preserve conflicts and unaffected human conclusions.
- Use `refresh-match` when an owning personal-data file changes. Re-evaluate only affected requirements and do not rewrite unchanged facts.
- Refresh never promotes a match from a roadmap entry. Verified work must first be written to the correct personal-data owner.

## Workflow: explicit roadmap handoff

1. Confirm that the user explicitly wants capability-gap planning.
2. Read [roadmap-handoff.md](references/roadmap-handoff.md).
3. Export only confirmed, worthwhile gaps; exclude `待确认` and low-value Preferred gaps by default.
4. Return `roadmap-handoff.json` to the independent `china-resume-growth-roadmap` Skill. Do not generate the learning plan here and do not modify role match state.

## Natural-language examples

**Exact JD:** “Use my career knowledge base at `/path/to/career-db` and this current JD to generate the default one-page recruiter and two-page technical Chinese resumes for Company A’s exact Backend Platform Engineer role, with ATS PDFs and per-variant provenance audits.”

**Extended profile:** “Generate the default resume variants and also include the opt-in three-page technical profile. Validate all three variants against their manifest page contracts.”

**Role only:** “I want to apply for Company B’s exact C++ Systems Engineer role, but I only have the role title and old hiring research. Generate the best evidence-backed targeted resume variants and make the source limitations explicit in each audit.”

**Analyze role:** “Analyze Company C’s AI Infrastructure Engineer opening against my personal career knowledge base and build the seven-file role dossier, but keep it run-local until I approve persistence.”

**Refresh:** “The official JD changed; refresh the role dossier, then refresh the evidence match for only the affected requirements without rewriting unchanged conclusions.”

**Handoff:** “Export the confirmed Critical and Major gaps from this role analysis as a roadmap handoff for my separate learning-plan Skill; do not create the plan or change my current match states.”

## Completion report

Report the resolved tier and target basis, run directory, `resume-variants.json`, produced variants and artifacts, omitted or pending claims, application blockers, and each variant's content/PDF acceptance results. Mention limitations and source freshness. Never claim ATS passage, interview success, or hiring probability.
