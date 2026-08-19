# Acme Platform Gaps

- Target role: [Acme Cloudworks Platform Engineer](../role-research/acme-cloudworks-platform-engineer/gap-analysis.md)
- Plan created: 2026-07-13
- Plan status: active
- Evidence effect: none

## Quartz Scheduler practice

- Source gap: REQ-QUARTZ, `明确缺口`, Major.
- Why worthwhile: company-specific explicit Required with interview and job impact.
- Tasks: study the fictional scheduler model; design synthetic retry and recovery scenarios; write a reviewable runbook; conduct a peer review.
- Completion criteria: reproducible synthetic incident exercise plus written review feedback.
- Boundary: completion does not prove production experience and does not change `明确缺口`. A later artifact may be recorded as lab evidence in the proper personal project owner, after which `refresh-match` may reassess without calling it production use.

## Kubernetes operations practice

- Source gap: PREF-K8S-1 / 2 / 3, `有知识无实践`, Major.
- Why worthwhile: repeated Preferred wording signals interview attention, but all three occurrences remain Preferred.
- Tasks: deploy a fictional service locally; observe it; perform rollback; diagnose an injected workload failure; document limits.
- Completion criteria: reviewable local lab artifact and deterministic failure notes.
- Boundary: checked tasks and completed status do not change `有知识无实践`; only verified owning evidence plus explicit `refresh-match` can trigger reassessment.

## Explicit exclusions

- RESP-5 collaboration (`待确认`, severity `null`) is a clarification item, not a learning task.
- CONSTRAINT-LOCATION (`unknown`) is an independent application constraint, not capability evidence or a learning task.
- PREF-ANIMATION (`明确缺口`, Minor) is a low-value Preferred and is deliberately excluded from handoff.
- No plan item writes to `evidence-mapping.md`.
