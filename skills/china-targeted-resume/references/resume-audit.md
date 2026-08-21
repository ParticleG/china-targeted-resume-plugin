# Resume and PDF Audit

Run deterministic content validation before rendering and deterministic PDF inspection after rendering. Core checks must work without an LLM.

## Content audits

**ATS:** one-column reading order; standard section names; natural, truthful keyword coverage; parseable dates, organizations, and titles; no essential text only in icons/images; every listed skill supported.

**HR:** target direction visible quickly; recent relevant experience first; key outcomes visible; career changes, vendor/client arrangements, gaps, and role changes not misleadingly packaged; appropriate density.

**Technical interview:** project context is clear; individual actions remain separate from team results; architecture and trade-offs are defensible; metric scope/source is preserved; skills can be demonstrated through projects.

**Truth and provenance:** every visible fact has a source ref; F4/F5/F6/P3 are absent; P2 appears only in confirmed targeted mode; verbs and metric qualifiers are preserved; company research has not become candidate experience; there are no unresolved placeholders.

**Privacy:** no credentials, internal addresses, customer data, private logs/repository locations, proprietary details, or inappropriate contact data; output/cache permissions are private.

### Visible claim readiness

Visible bullets are selected by owning section and standalone claim shape, not by a growing phrase blacklist. Prefer personal-work, results/metrics, and engineering/verification sections. Keep overview/background, technology-stack, key-decision context, system-boundary, responsibility-inventory, upstream, audit, provenance, limitation, and pending-confirmation sections in the dossier rather than the resume. Field-label records, diagrams, predicate-free technology inventories, and evidence-boundary negations are likewise dossier-only.

Selection preserves requirement importance, mapping priority, fact strength, match directness, and professional source relevance before applying the visible-claim quality priority. This prevents a cleaner but unrelated community claim from displacing mapped professional evidence.

The technical audit must emit `technical.resume_readiness` as an error when any manually supplied visible bullet fails the same readiness classifier. Filtering a record from the resume must not delete it from the evidence map or dossier.

## PDF acceptance

A PDF run succeeds only when all checks pass:

- page count does not exceed the requested limit;
- extracted text contains identity and every required section;
- Chinese text extracts without mojibake;
- extraction order follows the logical one-column document;
- fonts are embedded or safely handled by the renderer;
- email and selected public links are clickable annotations;
- no unresolved placeholder is present;
- body font and margins meet configured minima;
- preview shows no clipping, orphan heading, broken bullet, overflow, or pagination defect.

The presence of a PDF file is not acceptance. Return failures to content compression or rendering and inspect again.

## Compression order

When over budget: remove the lowest-priority bullet/project; merge repeated skills; compress older/weakly relevant experience; shorten summary; compress duplicated context; only then adjust spacing within template limits. Never solve overflow by dropping below minimum font or margin.

Report passed/failed checks and actionable reasons. Do not promise ATS passage, interviews, or offers.
