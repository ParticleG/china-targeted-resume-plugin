# Requirement Analysis

## Core responsibilities — explicit

| ID | Classification | Verbatim excerpt | Source span |
| --- | --- | --- | --- |
| RESP-1 | Responsibility | “Operate Linux services and participate in a shared incident-response rotation.” | `job-description.md#responsibilities`, bullet 1 |
| RESP-2 | Responsibility | “Build Python automation for delivery, diagnostics, and service lifecycle tasks.” | `job-description.md#responsibilities`, bullet 2 |
| RESP-3 | Responsibility | “Diagnose queue saturation, dependency failures, and database performance issues.” | `job-description.md#responsibilities`, bullet 3 |

## Required — explicit

| ID | Verbatim excerpt | Source span | Hard gate |
| --- | --- | --- | --- |
| REQ-LINUX | “Three or more years operating production Linux services.” | `job-description.md#required`, bullet 1 | capability |
| REQ-PYTHON | “Professional Python development experience.” | `job-description.md#required`, bullet 2 | capability |
| REQ-DOCKER | “Experience delivering containerized services with Docker.” | `job-description.md#required`, bullet 3 | capability |
| REQ-DATA | “Working knowledge of PostgreSQL and HTTP APIs.” | `job-description.md#required`, bullet 4 | capability |
| REQ-QUARTZ | “Direct production experience with Quartz Scheduler.” | `job-description.md#required`, bullet 5 | capability; the single occurrence remains Required |
| CONSTRAINT-LOCATION | “Ability to work from the Northbridge office three days each week.” | `job-description.md#required`, bullet 6 | application constraint; status `unknown` |

## Preferred — explicit

| ID | Verbatim excerpt | Source span |
| --- | --- | --- |
| PREF-K8S-1 | “Kubernetes experience supporting platform services.” | `job-description.md#preferred`, bullet 1 |
| PREF-K8S-2 | “Kubernetes experience improving deployment reliability.” | `job-description.md#preferred`, bullet 2 |
| PREF-K8S-3 | “Kubernetes experience diagnosing cluster workloads.” | `job-description.md#preferred`, bullet 3 |
| PREF-QUEUES | “Experience with metrics and distributed queues.” | `job-description.md#preferred`, bullet 4 |
| PREF-ANIMATION | “Familiarity with imaginary animation rendering workflows.” | `job-description.md#preferred`, bullet 5 |

The repeated Preferred keyword “Kubernetes” appears three times. Repetition is an anomaly/review signal only; it does not change classification, necessity, or hard-gate status. The single `Quartz Scheduler` occurrence remains Required.

## Inferred signals — not source requirements

| ID | Inference | Basis | Source | Confidence | Hard gate |
| --- | --- | --- | --- | --- | --- |
| INF-OWNERSHIP | The team likely values service ownership and written operational reasoning. | Incident rotation, runbooks, change reviews, and post-incident follow-up appear together. | `job-description.md#responsibilities` | high | no |
| INF-SCALE | Workloads may be bursty. | Queue saturation and fictional rendering batches are named. | `job-description.md#about-the-role`; responsibilities bullet 3 | medium | no |
| INF-COLLAB | Cross-team communication may be assessed. | Collaboration with product and studio integration teams is explicit as a responsibility. | responsibilities bullet 5 | medium | no |

## Application constraint

- Constraint: Northbridge office attendance three days each week.
- Source status: explicit Required.
- Candidate status: `unknown` because the personal preference record is stale.
- Recommendation effect: `pending_information`; satisfied technical capabilities cannot average it away.
- If confirmed impossible, set status to `unsatisfied` and list it as an application blocker without changing any Chinese evidence state.

## Ambiguities, conflicts, and red flags

- The current exact role conflicts with a stale 2024 third-party article that described Acme as fully remote.
- “Production” and “direct” are not quantified; do not infer a duration.
- No relocation support is stated.
- Preferred keyword repetition must not be interpreted as a hidden hard gate.
