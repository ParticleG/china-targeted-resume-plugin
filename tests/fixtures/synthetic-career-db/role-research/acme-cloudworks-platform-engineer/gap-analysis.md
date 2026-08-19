# Gap Analysis

Match state and severity are independent dimensions. Direct evidence does not mechanically create a gap.

| Requirement | Match state | Severity | Job / interview impact | Knowledge or practice needed | Observable verification | Roadmap |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-QUARTZ | 明确缺口 | Major | Company-specific Required may block capability fit. | Learn concepts, then complete hands-on failure and recovery scenarios; never claim production use from a lab. | Reviewed synthetic incident artifact and reproducible runbook, later recorded in the correct personal project owner. | [Acme platform gaps](../../growth-roadmap/acme-platform-gaps.md#quartz-scheduler-practice) |
| PREF-K8S-1 / 2 / 3 | 有知识无实践 | Major | Production-operation questions will expose the practice gap despite repeated Preferred classification. | Hands-on deployment, rollback, observation, and failure diagnosis. | Reviewable local lab artifact, then evidence-owner update. | [Acme platform gaps](../../growth-roadmap/acme-platform-gaps.md#kubernetes-operations-practice) |
| PREF-ANIMATION | 明确缺口 | Minor | Low-value Preferred may affect domain conversation only. | Optional vocabulary reading. | Short glossary if effort is later justified. | none; deliberately excluded from handoff |
| RESP-5 collaboration | 待确认 | null | The exact cross-team scenario requires clarification before a match can be stated. | Confirmation, not a learning plan. | A current owning record describing the relevant collaboration boundary. | none; never export unknowns |

## Application constraint diagnosis

| Constraint | Constraint status | Recommendation effect | Resolution |
| --- | --- | --- | --- |
| CONSTRAINT-LOCATION | `unknown` | `pending_information`; if `unsatisfied`, it becomes an application blocker | Obtain an explicit current answer; do not create a learning gap or Chinese match state. |

## Not gaps

REQ-LINUX, REQ-PYTHON, REQ-DOCKER, REQ-DATA, and PREF-QUEUES are not given gaps merely because matching uses different positive states.

## Handoff policy

Only confirmed, worthwhile gaps enter an explicitly requested handoff. For this fixture, REQ-QUARTZ and Kubernetes practice qualify; RESP-5 collaboration, CONSTRAINT-LOCATION, and low-value PREF-ANIMATION do not. No `roadmap-handoff.json` is committed.
