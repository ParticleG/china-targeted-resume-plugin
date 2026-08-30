# Roadmap Handoff Boundary

This Skill analyzes gaps. It does not generate a generic learning plan. Create `roadmap-handoff.json` only after an explicit user request for capability improvement or an explicit `export-roadmap-handoff` command.

## Eligible gaps

Export confirmed gaps only. Prioritize repeated core requirements across target roles, `有知识无实践` gaps that can yield verified artifacts, actionable `明确缺口` items with clear prerequisites, foundational blockers, and reusable capabilities aligned with the stated direction. Exclude `待确认` and low-value single-role Preferred gaps by default.

For each item include source role/gap refs, source requirement, exact canonical match state, severity, priority reason/role impact, current baseline evidence links, target capability/level, prerequisite gaps, suggested observable artifacts, verification signals, and intended personal-data owning file. Context may include deadline, hours per week, available environment, and learning preference.

## Downstream contract

The independent `china-resume-growth-roadmap` Skill may add prerequisite order, stage goals, current official resource URLs, role-scenario practice projects, concrete deliverables, estimated effort, observable pass criteria, validation methods, and the intended personal-data owner.

It must not reinterpret the JD, modify the seven dossier files' ownership, change canonical state, fabricate personal facts, treat a plan/course/time/confidence as evidence, or update `evidence-mapping.md` directly.

## Required transaction order

1. Generate and confirm the growth roadmap.
2. Perform the work and produce a real artifact.
3. Verify execution, tests/deployment/performance/fault analysis/documentation and contribution boundary.
4. Write the verified result to the correct personal-data owning file.
5. Run `refresh-match`.
6. Let evidence mapping and gap analysis update from the new owner.

A roadmap never owns capability facts and never upgrades a current match. Handoff export must not become an implicit dependency of `generate`.
