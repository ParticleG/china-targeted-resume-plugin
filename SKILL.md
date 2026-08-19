---
name: china-targeted-resume
description: Use this Skill whenever a user wants to turn a personal career knowledge base into an evidence-grounded master resume, public portfolio resume, or resume for a target company and role, even if they only mention choosing a company, an exact role, a JD, job fit, role research, refreshing stale role or evidence analysis, or handing confirmed gaps to a roadmap Skill. It discovers the source, builds or refreshes the seven-file role dossier, applies China recruiting context and strict evidence/privacy gates, generates and audits master/targeted/ATS resumes, and validates a local PDF. Trigger aggressively for candidate-side personal career evidence and resume or target-role work. Require an explicit request before roadmap handoff. Do not use for generic PDF conversion, recruiter-side candidate screening, or generic learning/onboarding/interest plans.
---

# China Targeted Resume

For human-facing installation, CLI tutorials, output discovery, and troubleshooting, see [README.md](README.md).

Orchestrate the deterministic `china-targeted-resume` CLI and use language reasoning only where requirement interpretation or resume composition needs it. The personal career knowledge base remains the source of truth; generated resume text never writes back to `personal-data/`.

## Non-negotiable boundaries

- Treat the configured career repository as read-only runtime input unless the user explicitly confirms a proposed seven-file role-dossier write. Never copy it into this Skill.
- Write generated artifacts outside the source root. Directories containing personal data use mode `0700`; files use `0600`.
- Persist navigation metadata only. Never persist source section bodies, contacts, derived claims, F6/P3 material, or secrets in indexes, caches, logs, traces, temporary workspaces, or prompt files.
- Use only these role match values: `已有直接证据`, `可迁移经验`, `有知识无实践`, `明确缺口`, `待确认`.
- Keep capability match, real-world application constraints, and gap severity independent. Constraints use only `satisfied`, `unsatisfied`, `unknown`, `not_applicable`; severity uses only `Critical`, `Major`, `Minor`, or null.
- Do not invent facts, upgrade contribution verbs, broaden metric scope, turn company research into candidate experience, or treat a plan as evidence.
- Core deterministic CLI operations must run without an LLM. Do not replace CLI validation with prose review.
- A requested `zh-CN` resume must contain concise Chinese prose, not merely `locale: zh-CN`. When source claims are in another language, translate only the run-local visible `ResumeDocument` strings, preserve every `claim_id`, provenance reference, contribution verb, metric qualifier, name, and conventional technology term, then rerun content/PDF validation. Translation never changes evidence or match state.
- Roadmap creation is outside this Skill. Export a handoff only after an explicit request; never silently invoke a learning-plan Skill.

## Start here

1. Identify the source root, requested output mode, target company/role, JD source, page count, template, and output root from the request.
2. Read [source-adapter.md](references/source-adapter.md) before discovering or searching a career repository.
3. If the target is ambiguous, use `list-companies` and `list-roles`, present the choices, and stop for selection. Never silently pick among multiple candidates.
4. Read [role-resolution.md](references/role-resolution.md), resolve Tier A-D, and record the exact `target_basis`.
5. Load only the detailed references required by the workflow below.
6. Run the CLI operation. Treat its structured artifacts as the execution record.
7. Ask only high-value confirmation questions, then continue or omit unresolved claims.
8. Run deterministic content and PDF validation before reporting success.

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
| Apply China-market wording and risk context | [china-recruiting-context.md](references/china-recruiting-context.md) |
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
  --mode targeted_application \
  --pages 2 \
  --template ats-simple \
  --output OUTPUT_ROOT
```

Add `--export-roadmap-handoff` only when the user explicitly asks for that handoff. Prefer the separate export command after gaps have been reviewed.

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
china-targeted-resume render --document RUN_DIR/resume-document.json [--output RUN_DIR/resume.pdf]
china-targeted-resume inspect-pdf --pdf RUN_DIR/resume.pdf
```

## Workflow: exact JD

1. Resolve Tier A only when company, exact role, and a complete current JD are all available.
2. Read the dossier, requirement, competency, evidence, gap, output, audit, and privacy references.
3. Preserve explicit JD quotes and source spans; keep inferences separate.
4. Build the complete requirement-to-evidence matrix and report explicit coverage with its calculation.
5. Confirm selected P2 material and uncertain high-impact claims.
6. If the requested output language differs from selected source prose, translate only the run-local visible strings under the rule above; never translate by strengthening or summarizing a claim.
7. Generate, validate, render, and inspect. Confirm the requested language is actually present in extracted PDF text. A PDF file existing is not success; every acceptance check must pass.

## Workflow: role only

1. Resolve an exact role with partial, old, company-level, or absent JD evidence as Tier B.
2. Use the exact role identity plus dated company recruiting, technology, business, and archived role sources.
3. Continue generation; set `explicit_requirement_coverage` and `coverage_calculation` to null.
4. Mark missing requirements, source age, conflicts, inference emphasis, and limitations in audit artifacts, not visible resume prose.
5. Keep inferred requirements out of hard gates.
6. Generate and validate the targeted resume and PDF.

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
4. Return `roadmap-handoff.json` to an independent roadmap Skill. Do not generate the learning plan here and do not modify role match state.

## Natural-language examples

**Exact JD:** “Use my career knowledge base at `/path/to/career-db` and this current JD to generate a two-page Chinese resume for Company A’s exact Backend Platform Engineer role, with an ATS PDF and provenance audit.”

**Role only:** “I want to apply for Company B’s exact C++ Systems Engineer role, but I only have the role title and old hiring research. Generate the best evidence-backed targeted resume and make the source limitations explicit in the audit.”

**Analyze role:** “Analyze Company C’s AI Infrastructure Engineer opening against my personal career knowledge base and build the seven-file role dossier, but keep it run-local until I approve persistence.”

**Refresh:** “The official JD changed; refresh the role dossier, then refresh the evidence match for only the affected requirements without rewriting unchanged conclusions.”

**Handoff:** “Export the confirmed Critical and Major gaps from this role analysis as a roadmap handoff for my separate learning-plan Skill; do not create the plan or change my current match states.”

## Completion report

Report the resolved tier and target basis, run directory, produced artifacts, omitted or pending claims, application blockers, audit result, and PDF acceptance result. Mention limitations and source freshness. Never claim ATS passage, interview success, or hiring probability.
