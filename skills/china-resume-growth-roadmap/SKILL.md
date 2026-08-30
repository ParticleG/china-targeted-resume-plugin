---
name: china-resume-growth-roadmap
description: Use only after the user explicitly asks to turn a validated china-targeted-resume roadmap-handoff.json into a capability growth plan with staged practice, official learning resources, deliverables, effort ranges, and verification criteria. Never use a plan as current resume evidence or mutate role/evidence state.
---

# China Resume Growth Roadmap

Consume the private `roadmap-handoff.json` produced by `china-targeted-resume export-roadmap-handoff`. This Skill is a downstream planner. It does not reinterpret the JD, candidate source, requirement classification, match state, gap severity, or evidence policy.

## Preconditions

- Require an explicit user request for a growth plan.
- Read only the handoff artifact and user-supplied planning constraints. Do not discover the personal career repository.
- Refuse `待确认` or direct-evidence items. Preserve every input `gap_id`, `requirement_id`, match state, severity, baseline reference, target capability, artifact suggestion, verification signal, and intended owning file.
- Keep output outside the career source root in a private directory (`0700`) with private files (`0600`).

## Planning inputs

Ask only when material and not already supplied: deadline, hours per week, available environment, preferred language, budget, and whether production-like infrastructure is available. Never ask the user to paste credentials, private source text, customer data, or internal systems.

## Plan construction

For each eligible gap, produce ordered stages:

1. **Baseline:** define the exact current boundary and a reproducible starting check.
2. **Learn:** select the minimum concepts needed for the target capability.
3. **Practice:** build a bounded role-scenario artifact; do not label a lab as production experience.
4. **Verify:** run tests, deployment, benchmark, fault analysis, documentation review, or peer review matching the handoff signals.
5. **Record:** after real completion, propose a factual update to the intended personal-data owner for separate user review.
6. **Refresh:** run `refresh-match` only after the verified source owner is updated.

Each stage must include objective, prerequisite, concrete work, expected artifact, observable pass criteria, effort range, and failure/retry condition. Order prerequisite gaps before dependent gaps and prefer reusable requirements shared by multiple roles.

## Learning resources

Research current resources at planning time. Prefer official documentation, official tutorials, standards, maintainers' guides, and reputable course providers. For every URL record title, publisher, access date, target stage, and why it fits the exact gap. Reject stale, inaccessible, purely promotional, or scope-mismatched resources. A course completion certificate is not capability evidence unless the role explicitly requires that certificate.

## Deterministic validation and write boundary

Build the candidate plan against `schemas/growth-roadmap.schema.json`. Compute `source_handoff_sha256` from the exact bytes of the private handoff file. Preserve every handoff-owned field byte-for-value at the semantic model boundary; do not paraphrase `target_capability`, change severity/state, replace evidence refs, or redirect the intended owner.

Write the draft plan to one private `0600` JSON input, then invoke the sole artifact writer:

```bash
china-targeted-resume write-growth-roadmap \
  --source SOURCE_ROOT \
  --handoff /private/path/roadmap-handoff.json \
  --plan /private/path/draft-growth-roadmap.json \
  --output OUTPUT_ROOT
```

The command must validate input ownership/mode/size, the exact handoff hash, one plan per handoff gap, preserved handoff fields, six ordered stages, non-empty HTTPS learning resources, prerequisite references, effort ranges, safe owning paths, and the no-evidence-elevation invariant. It then allocates a new `0700` timestamped directory and atomically writes `0600` `growth-roadmap.json`, `growth-roadmap.md`, and `growth-roadmap.validation.json`. Never write final artifacts directly or overwrite an earlier run.

## Output contract

The validated JSON includes:

- `schema_version`, creation time, exact source handoff hash, and user planning constraints;
- one plan per preserved `gap_id`;
- exact handoff `priority_reason`, `suggested_artifacts`, and `verification_signals` without loss or paraphrase;
- the ordered `baseline`, `learn`, `practice`, `verify`, `record`, and `refresh` stages;
- non-empty resource records with title, publisher, HTTPS URL, access date, target stage, authority type, and relevance;
- artifacts, pass criteria, effort ranges, prerequisites, and intended owning file;
- `completion_does_not_change_match_state: true`;
- post-completion action: verify the real artifact, update the owning source with user approval, then run `refresh-match`.

Report success only when `growth-roadmap.validation.json` has `success: true`, positive plan/stage/resource counts, and the returned paths are private. Never write into `personal-data/`, `role-research/`, or the seven-file dossier. Never claim that a planned, simulated, local, or course exercise is production practice. Never rewrite the resume from the plan.
