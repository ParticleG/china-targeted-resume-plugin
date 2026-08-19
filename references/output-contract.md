# Output Contract

All outputs are downstream artifacts in a private run directory outside the source root. They never become evidence and generated resume text never writes back to `personal-data/`.

## Modes and permissions

- `targeted_application`: P0, safe P1, and explicitly confirmed target-purpose P2 may be used.
- `public_portfolio`: P0 and safe P1 only; omit phone by default and exclude P2.
- `master_resume`: private comprehensive selection, clearly non-targeted; fact and P3 gates still apply.

Create personal-data directories with `0700` and files with `0600`. Do not log bodies or personal details.

## Run artifacts

A complete targeted run may contain run/source/target metadata; run-local seven-file role dossier; JD snapshot; requirements, competencies, constraints, evidence map, gaps, recommendation; provenance; confirmation questions; audit report; `resume-document.json`; targeted Markdown; ATS text; HTML; PDF; preview; and interview questions. Generate `roadmap-handoff.json` only on explicit request.

Tier and available evidence determine which artifacts are meaningful. Tier B keeps explicit coverage null; Tier C marks drafts and avoids role-level coverage; Tier D lists choices or explicitly generates a master resume.

## Resume document boundary

The renderer consumes only `resume-document.json`, containing schema/locale, target metadata, contact, headline, summary, grouped skills, experience, projects, education, honors, links/provenance refs, and render policy. Internal experience/project bullets retain claim IDs for provenance validation; templates do not display those IDs.

Default visible order is contact/headline, two-to-three-line summary, evidence-backed skills, work experience, selected projects, education/honors, and verified relevant links. Each project gives short product/system context followed by personal action, deliverable, decision/trade-off, and bounded result.

## Composition rules

Target by selecting and ordering facts, not rewriting history. Prefer direct evidence, then clearly framed transferable evidence. Use JD terminology only when true. Preserve titles, dates, contribution level, metric precision, and confidentiality. Exclude unresolved claims/placeholders.

Use one-column A4 templates. Page budget affects content selection before typography. Keep required minimum body font and margins.

## Completion

A run is complete only after provenance coverage, deterministic content validation, render, and PDF inspection pass. Report target basis, limitations, output paths, omitted/pending claims, blockers, and validation results. A generated file alone is not proof of acceptance.
