# Seven-File Role Dossier Contract

Create a run-local dossier for every role analysis. Persist it under `role-research/<company-role-slug>/` only when persistence was requested and the user confirms the proposed content.

Exactly seven files own the dossier:

| File | Sole ownership | Must not contain |
| --- | --- | --- |
| `job-description.md` | Company, department, exact role, location, level, publish/access dates, recruiting status, source metadata, and the single full verbatim JD copy | Candidate matching, rewritten JD, resume prose |
| `requirement-analysis.md` | Explicit Required/Preferred/responsibilities/soft/domain items; separately sourced inferences and anomalies | Candidate facts, unsourced hard gates, full JD copy |
| `competency-model.md` | Expected capability, depth, scale, responsibility scope, problem context, and validation signals | Judgments about whether the candidate has them |
| `evidence-mapping.md` | Requirement-to-personal-evidence mapping, exact canonical Chinese state, owning links, evidence boundaries, and questions | Learning plans, positive matches without owning links, English/alternate states |
| `gap-analysis.md` | Independent Critical/Major/Minor impact, priority, validation direction, and roadmap references | Mechanical gaps for every Preferred item; plans presented as capability |
| `interview-preparation.md` | Project deep dives, systems/fundamentals/domain/debugging/behavior questions, questions for interviewers | New personal facts or unsupported model answers |
| `sources.md` | Source title, URL/path, publisher, dates, type, trust, bias, freshness, conflicts, and use | Unsourced conclusions or copied personal facts |

The full JD appears only in `job-description.md`. Other files refer to requirement IDs, short necessary quotes, summaries, and relative links.

## Identity and provenance

Use stable IDs for requirements, competencies, constraints, evidence, and gaps. Every explicit requirement keeps a verbatim quote and source span. Every inference keeps its textual basis, source, confidence, and explicit `origin=inferred`. Every positive evidence match resolves to a `personal-data/` owner and section/hash.

## Run-local and persistent behavior

The run-local IR is the working truth for a run. Before persistence, show additions/changes and confirm. Never write generated resume text to `personal-data/`. Preserve manually reviewed unaffected conclusions during refresh.

`refresh-role` compares source hashes and rebuilds only affected requirements and dependents. An official current source may outrank an old source, but conflicts remain recorded. `refresh-match` responds to changed personal evidence owners and leaves unrelated mappings untouched.

## Boundary audit

Reject a dossier if the JD is duplicated, a competency contains candidate judgment, a positive match lacks an owning link, a gap conflates status with severity, interview preparation invents facts, or sources contain unsourced conclusions/personal-data copies.
