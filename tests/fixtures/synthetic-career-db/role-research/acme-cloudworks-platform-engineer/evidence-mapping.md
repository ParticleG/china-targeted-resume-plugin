# Evidence Mapping

Only the five exact canonical Chinese values below are valid. Severity is owned by `gap-analysis.md`, not inferred from state.

| Requirement | Necessity | Match state | Evidence | Rationale |
| --- | --- | --- | --- | --- |
| REQ-LINUX | Required | 已有直接证据 | [Orbit Orchard incident response](../../personal-data/work/orbit-orchard-experience.md#incident-response) | Production Linux service operation and incident rotation are directly recorded. |
| REQ-PYTHON | Required | 已有直接证据 | [Lantern Queue engineering](../../personal-data/projects/lantern-queue.md#engineering-and-verification) | Python API and operational tooling are directly recorded. |
| REQ-DOCKER | Required | 已有直接证据 | [Orbit Orchard delivery platform](../../personal-data/work/orbit-orchard-experience.md#delivery-platform) | Container delivery with Docker is directly recorded. |
| REQ-DATA | Required | 可迁移经验 | [Lantern Queue architecture](../../personal-data/projects/lantern-queue.md#system-architecture) | PostgreSQL and HTTP experience is directly relevant, while exact Acme operating context differs. |
| REQ-QUARTZ | Required | 明确缺口 | — | No owning evidence shows Quartz Scheduler use; distributed queue experience must not be renamed as direct Quartz experience. |
| PREF-K8S-1 / 2 / 3 | Preferred | 有知识无实践 | [Capabilities](../../personal-data/profile/capabilities.md#verified-capabilities) | Kubernetes concepts are recorded as study only, with no production operation. |
| PREF-QUEUES | Preferred | 已有直接证据 | [Lantern Queue architecture](../../personal-data/projects/lantern-queue.md#system-architecture) | Queue design and metrics are directly recorded. |
| PREF-ANIMATION | Preferred, low value | 明确缺口 | — | No fictional animation workflow familiarity; low-value Preferred and not a roadmap priority. |
| RESP-5 collaboration | Responsibility | 待确认 | — | The source requires collaboration with product and studio integration teams, but the available evidence does not confirm that exact cross-team scenario. Match severity is `null`. |

## Application constraints — separate from capability evidence

| Constraint | Source classification | Constraint status | Evidence | Recommendation effect |
| --- | --- | --- | --- | --- |
| CONSTRAINT-LOCATION | Required | `unknown` | [Stale preferred location](../../personal-data/meta/dynamic-facts.md) | `pending_information`; if confirmed `unsatisfied`, treat as an application blocker. |

Application constraints use only `satisfied`, `unsatisfied`, `unknown`, or `not_applicable`. They never use or alter the five Chinese capability match states.

## Excluded source facts

F4 and F5 claims are excluded from positive evidence. F6/P3 content must not be retrieved into prompts or outputs. P2 evidence may be considered only in targeted Acme mode and is not needed for the mappings above.

## Refresh boundary

A completed roadmap task does not edit this file. Reassessment occurs only after an actual verified artifact is written to its correct `personal-data/` owning file and `refresh-match` is explicitly run. Unchanged rows remain byte-for-byte stable.
