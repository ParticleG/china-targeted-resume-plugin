# Source Adapter Contract

Use this reference when discovering a career knowledge base, listing companies or roles, building a navigation index, or retrieving evidence.

## Adapter responsibilities

A source adapter must discover a repository, list and load company/role references, resolve a target, load policy, search candidate evidence, load an exact evidence section, and verify public links. The pipeline depends on this interface rather than one person's paths.

For `markdown-career-v1`, validate these navigation and policy documents before use:

- root `README.md` or `README.zh-CN.md`;
- `personal-data/README.md` and `personal-data/meta/fact-boundaries.md`;
- `company-research/README.md`;
- `role-research/README.md`;
- `growth-roadmap/README.md`.

`role-research/skill-assisted-job-match-workflow.md` is a legacy human workflow, not a runtime authority. If a repository README links to a removed historical version, inspect it through version control when needed; do not mutate the source root merely to satisfy adapter discovery.

Useful navigation seeds include profile basics, career timeline, capabilities, verifiable achievements, work summaries, and public links. They locate owners; they do not replace owning evidence documents.

## Personal-data owning boundaries

Resolve every claim to the narrowest owner:

| Owner | What it owns |
| --- | --- |
| `profile/basic-information.md` | current identity, contact, location, headline inputs |
| `profile/career-timeline.md` | employment/project chronology and role dates, not detailed claims |
| `profile/capabilities.md` | categorized capability statements and their stated boundaries |
| `profile/verifiable-achievements.md` | verified outcomes, metrics, awards, and evidence pointers |
| `work/*.md` | employment context and links to detailed company-project owners |
| `company-projects/*.md`, `personal-projects/*.md`, `community-projects/*.md` | detailed project context, actions, contribution, technology, results, limitations |
| `meta/public-links.md` | URL ownership, audience, and current verification state |

`meta/fact-boundaries.md` owns policy, not resume facts. Navigation summaries never authorize broadening a detailed owner's wording.

## Metadata-only index

A persistent index may contain only navigation metadata such as document ID, source-relative path, source hash, title, section heading/anchor, domain, and internal outgoing links. It must not contain source section text, contact details, extracted facts, derived claims, F6/P3 content, credentials, or prompts.

Use two-stage retrieval:

1. Recall candidate files from metadata, headings, titles, and relative links.
2. In the current process only, scan the minimum candidate sections after local F6/P3 and secret filtering.
3. Re-read the owning section and bind each accepted claim to path, section/anchor, and source hash.
4. Discard section bodies when the process ends.

Never load the entire private repository into one prompt or create a second full-text database.

## Company and role sources

Company research may guide project/skill ordering, summary emphasis, business vocabulary, interview preparation, and open questions. It never proves a candidate fact.

Resolve role material in this priority order: user JD text, user JD file, current official JD URL, existing exact role dossier, exact entry in company hiring research, then company/role-family evidence. Preserve source title, path/URL, publisher, published date, accessed date, type, freshness, and conflicts.

## Path and refresh safety

- Canonicalize paths and require every source read to remain under the configured source root.
- Reject traversal and symlinks escaping the root. Treat external URLs as references, not paths.
- Exclude Git internals, output roots, ignored secrets, credentials, and generated artifacts.
- Persist outputs and indexes outside the source root with private permissions.
- Use source hashes for refresh. `refresh-role` updates only target-source dependents; `refresh-match` updates only requirements dependent on changed owning evidence.
- Never overwrite source sections with generated resume text.
