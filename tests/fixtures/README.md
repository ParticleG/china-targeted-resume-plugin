# Synthetic Fixture Policy

`synthetic-career-db/` is a Markdown-only career database for automated tests. Every person, employer, product, address, token, metric, and URL is deliberately fictional. The reserved `.invalid` domains cannot identify real services. Do not replace any fixture value with production or personal data.

## Test-matrix input map

| Case | Fixture input |
| --- | --- |
| 1. Complete current JD | `role-research/acme-cloudworks-platform-engineer/job-description.md` plus direct mappings |
| 2. Exact old/partial role | `company-research/clockwork-capybara-robotics/roles-and-hiring.md` |
| 3. Adjacent domain and major gaps | Clockwork Capybara dossier, `tidal-rover-lab.md`, and Acme gap rows |
| 4. Fact/publicity exclusion | `personal-data/meta/fact-boundaries.md`, capabilities, and work F4/F5/F6/P2/P3 rows |
| 5. Metric precision | Work, achievements, and Lantern Queue approximate/range/stage/team metrics |
| 6. Dynamic and stale facts | `personal-data/meta/dynamic-facts.md` and active/broken/stale public links |
| 7. One-page overflow | Profile, projects, education, honors, and explicit low-priority content |
| 8. ATS reading order | `personal-data/README.md` composition sequence and text-only content |
| 9. Source isolation | Traversal link below, F6/P3 markers, and symlink setup below |
| 10. Five-state round trip | Acme `evidence-mapping.md` contains all exact canonical values |
| 11. Required/Preferred fidelity | Complete JD repeats Kubernetes three times under Preferred and Quartz Scheduler once under Required |
| 12. Explicit/inferred isolation | Acme `requirement-analysis.md` with quotes, spans, basis, source, and confidence |
| 13. State/severity orthogonality | Acme `gap-analysis.md`, including `有知识无实践` + Major, `明确缺口` + Minor, and `待确认` + null |
| 14. Hard constraint | Northbridge attendance is Required and independently `unknown` |
| 15. Non-formula recommendation | Workflow and partial role require multidimensional output and `null` explicit coverage |
| 16. Seven-file ownership | The single Acme role directory contains exactly the seven contract files |
| 17. Roadmap handoff | Gap analysis distinguishes worthwhile confirmed, unknown, and low-value Preferred gaps; no JSON handoff is committed |
| 18. Plan non-elevation | `growth-roadmap/acme-platform-gaps.md` repeatedly records no evidence effect |
| 19. Incremental refresh/conflict | Acme role sources contain hashes, update boundaries, and retained current-vs-stale conflict |
| 20. Role-family/company difference | Both technology dossiers and Acme competency model separate baseline inference from company-only Quartz Scheduler |

## Path-isolation setup

A traversal link is intentionally present in `synthetic-career-db/personal-data/meta/public-links.md`. Tests must reject it before reading outside the configured source root.

A symlink escape is intentionally documented rather than committed so this repository remains safe and portable. A test that supports symlinks may create `synthetic-career-db/personal-data/meta/escape-link.md` as a symlink to a temporary file outside `synthetic-career-db`, assert that canonical-path validation rejects it, and remove it in fixture teardown. The temporary file must contain only synthetic text.

No fixture contains executable code. Fixture readers must never persist source section bodies, contact details, F6/P3 facts, or secrets in indexes, caches, logs, traces, or temporary workspaces.
