# Role Resolution and Tiering

Resolve the best available target basis transparently. A complete current JD improves precision but is not a prerequisite for useful generation.

## Source priority

Use, in order: user-provided JD text; user-provided local JD file; current official JD URL; existing exact role dossier; exact role in company hiring research; company technology/hiring role-family evidence. Keep source dates, access dates, status, hashes, and conflicts.

## Tier A — `exact-current-jd`

Requires selected company, exact role/name or ID, and a complete current JD. Parse every explicit requirement, separate inferences, build a complete requirement-to-evidence matrix, and report explicit coverage and evidence strength. Targeted resume and accepted PDF are allowed.

## Tier B — `exact-role-partial-evidence`

Requires selected company and exact role, with incomplete/old JD, company research, archived evidence, or no full JD. Continue targeted resume and PDF generation. Set `explicit_requirement_coverage` and `coverage_calculation` to null. Record missing requirements, source dates, staleness, conflicts, inferred emphasis, and limitations in target/audit artifacts. Never promote an inference to a company hard gate. This is a supported core flow, not an error fallback.

## Tier C — `company-role-family`

Requires company plus a meaningful role family but no exact role. Offer exact local choices first. If the user requests a draft without choosing, produce a company/role-family targeted draft and PDF with reduced confidence. Do not claim role-level requirement coverage or company-specific hard gates from role-family inference.

## Tier D — `insufficient-target`

Company or valid role direction is missing. List local companies/roles and request a selection. Do not calculate a misleading match score. Generate a general `master_resume` only when explicitly requested and label it as non-targeted.

## Coverage and recommendation rules

Every run records target basis, company/role, JD completeness, source/check dates, evidence coverage summary, staleness risk, conflicts, and limitations. Tier A may calculate explicit coverage from complete explicit requirements. Tier B/C may not fabricate it.

Default to a multidimensional recommendation: target-source completeness, hard-constraint readiness, evidence strength, Critical/Major gaps, pending information, and rationale. Allowed decisions are `apply_now`, `apply_with_risks`, `deprioritize`, and `pending_information`. A requested number must disclose weights, denominator, unknown items, source completeness, calculation, and `heuristic=true`; it is not hiring probability. Never use a fixed Required/Preferred formula or fixed application threshold.

## Ambiguity and refresh

When natural language resolves to multiple companies or roles, present choices and stop for selection. Do not silently optimize for the seemingly strongest match. Current official sources outrank old snapshots and third-party summaries, but record conflicts rather than erasing them.
