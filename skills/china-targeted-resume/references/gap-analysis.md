# Gap, Constraint, and Application Analysis

Keep three dimensions independent: evidence match state describes current evidence; severity describes role impact; application constraints describe practical eligibility.

## Severity

Use only:

- `Critical`: explicit license, location, hard qualification, or genuinely non-substitutable core capability that can block application.
- `Major`: substantial deficit in a core responsibility/capability with a realistic migration or improvement path.
- `Minor`: low-weight capability, Preferred item, or issue that does not change the main application judgment.

`待确认` has null severity until information is resolved. `已有直接证据` normally creates no gap; record freshness, evidence quality, or interview risk separately. Do not mechanically create a gap for every Preferred item.

Each gap links its requirement, canonical Chinese match state, severity, role impact, reason, baseline evidence refs, validation direction, priority, and optional roadmap refs.

## Independent constraints

Use `satisfied`, `unsatisfied`, `unknown`, or `not_applicable` for location, work mode, language, education, certificate/license, work authorization, travel, start date, and salary. Include whether the constraint is a hard gate, candidate/required values, current evidence, check date, and impact.

An unsatisfied hard constraint becomes an explicit application blocker. An unknown hard constraint remains pending information. Neither may be averaged away by technical strengths. Never serialize canonical Chinese evidence states as constraint status.

An experience-duration threshold remains an explicit requirement, not an application constraint. The requirement side must be parsed from one atomic numeric verbatim quote/span. The candidate side must be parsed from a current selected `EvidenceRecord` with owning source path/hash/span and an extractive atomic duration fact containing its checked date. The binding's candidate scope/years/check time must match every referenced record, and its required scope/minimum/maximum must match the requirement. Reject arbitrary IDs, self-reported numbers, records without duration facts, altered thresholds, compound/free-text scope, inferred requirements, missing audit data, and mismatched evidence. Only a verified shortfall of at most 25% supports `apply_with_risks`; logistics/eligibility hard constraints remain independently blocking.

## Recommendation

Use `apply_now`, `apply_with_risks`, `deprioritize`, or `pending_information`, supported by target-source completeness, hard-constraint readiness, explicit coverage when valid, evidence strength, Critical/Major gaps, pending information, and concise rationale.

Default to this multidimensional diagnosis, not one percentage. If a user explicitly asks for a number, disclose every weight, denominator, unknown, source-completeness limitation, and calculation; label it `heuristic=true`. It is neither hiring probability nor a factual property of the candidate.

Keep gaps in audit and interview preparation unless their truthful framing improves the resume (for example, explicitly transferable adjacent experience). Never fabricate direct domain experience to hide a gap.
