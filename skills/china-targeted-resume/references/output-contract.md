# Output Contract

All outputs are downstream artifacts in a private run directory outside the source root. They never become evidence and generated resume text never writes back to `personal-data/`.

## Modes and permissions

- `targeted_application`: P0, safe P1, and explicitly confirmed target-purpose P2 may be used.
- `public_portfolio`: P0 and safe P1 only; omit phone by default and exclude P2.
- `master_resume`: private comprehensive selection, clearly non-targeted; fact and P3 gates still apply.

Create personal-data directories with `0700` and files with `0600`. Do not log bodies or personal details.

## Run artifacts and discovery

Every generation creates the recruiter one-page (`resume-recruiter-1p`) and technical two-page (`resume-technical-2p`) variants. Generate the extended three-page technical profile (`technical-profile-3p`) only when `include_extended_profile` or the CLI's `--include-extended-profile` is explicitly selected.

`resume-variants.json` is the authoritative run manifest. Consumers must use its variant entries, concrete template, page targets, actual page counts, validation results, artifact paths, and preview paths for discovery instead of guessing filenames.

Each listed base name owns a complete artifact set:

```text
<base>.document.json
<base>.provenance.json
<base>.validation.json
<base>.audit.md
<base>.md
<base>.txt
<base>.html
<base>.pdf
<base>.preview.png, followed by <base>.preview-2.png, <base>.preview-3.png, and so on
```

Shared run artifacts may include run/source/target metadata; a run-local seven-file role dossier; JD snapshot; requirements, competencies, constraints, evidence map, gaps, recommendation; confirmation questions; and interview questions. Generate `roadmap-handoff.json` only on explicit request.

Tier and available evidence determine which artifacts are meaningful. Tier B keeps explicit coverage null; Tier C marks drafts and avoids role-level coverage; Tier D lists choices or explicitly generates a master resume.

## Resume document boundary

Each renderer invocation consumes one variant's `<base>.document.json`, containing schema/locale, variant and target metadata, contact, headline, summary, grouped skills, experience, projects, education, honors, links/provenance refs, and render policy. Internal experience/project bullets retain claim IDs for provenance validation; templates do not display those IDs.

Default visible order is contact/headline, two-to-three-line summary, evidence-backed skills, work experience, selected projects, education/honors, and verified relevant links. Each project gives short product/system context followed by personal action, deliverable, decision/trade-off, and bounded result.

## Composition rules

Target by selecting and ordering facts, not rewriting history. Prefer direct evidence, then clearly framed transferable evidence. Use JD terminology only when true. Preserve titles, dates, contribution level, metric precision, and confidentiality. Exclude unresolved claims/placeholders.

The variants are independently composed for distinct readers and depth. Keep every A4 template semantic and single-column. The `adaptive` request strategy resolves to `ats-simple` for the recruiter one-page variant and `human-readable` for the technical two-page and optional extended three-page variants; each `ResumeDocument` and manifest entry records only the resolved concrete template. Each variant's page budget affects content selection before typography, and required minimum body font and margins remain enforced.

## Completion

A run is complete only after every manifest-listed variant passes its own provenance coverage, deterministic content validation, render, and PDF page-contract inspection. A source-sparse variant may pass below its target only when it is explicitly marked `underfilled`; never pad it with unsupported content. Report target basis, limitations, manifest and output paths, omitted/pending claims, blockers, and per-variant validation results. A generated file alone is not proof of acceptance.
