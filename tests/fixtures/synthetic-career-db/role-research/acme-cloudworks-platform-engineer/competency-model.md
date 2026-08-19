# Competency Model

This file models the role only. It contains no candidate match, evidence state, or personal-data claim.

## Reusable platform-engineering baseline

| Capability | Expected level | Evaluation scenario | Gate / bonus | Basis |
| --- | --- | --- | --- | --- |
| Linux service operations | independent | Diagnose a failing service and explain recovery | gate | explicit Required and responsibility |
| Python automation | independent | Design a safe lifecycle automation task | gate | explicit Required |
| Container delivery | working | Explain image-to-service delivery and rollback | gate | explicit Required |
| Data and API operations | working | Investigate PostgreSQL and HTTP dependency symptoms | gate | explicit Required |
| Incident reasoning | working | Triage saturation and communicate decisions | gate | explicit responsibility |
| Observability | working | Select signals and improve a runbook | bonus | responsibility and Preferred |
| Distributed queues | working | Reason about retries, leases, and saturation | bonus | Preferred |
| Kubernetes operations | working | Diagnose a hypothetical cluster workload | bonus | repeated Preferred; repetition changes nothing |

## Acme-specific difference

| Capability | Expected level | Evaluation scenario | Gate / bonus | Basis |
| --- | --- | --- | --- | --- |
| Quartz Scheduler production operation | direct production | Explain an actual production incident or change | gate | Acme explicit Required; not inherited by other companies |
| Animation rendering workflow familiarity | introductory | Map a fictional batch lifecycle | bonus | Acme explicit Preferred |

## Application constraint model

Northbridge attendance is evaluated independently as `satisfied`, `unsatisfied`, `unknown`, or `not_applicable`. It is not a competency and is never averaged with the capability rows.
