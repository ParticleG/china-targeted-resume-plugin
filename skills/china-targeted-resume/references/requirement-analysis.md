# Requirement Analysis

Analyze what the target source says before considering candidate evidence.

## Required fields

Each requirement needs a stable ID, normalized text, category, necessity, priority, origin, source reference, business context, confidence, and `hard_gate`. Explicit items also require the verbatim quote and exact source span. Inferred items require a compact inference basis and source; do not present them as JD text.

Categories may include hard qualification, core responsibility, core skill, business/domain, tool/platform, collaboration/delivery, preferred qualification, inferred context, and risk/ambiguity.

## Preserve source semantics

- Classify Required, Preferred, responsibilities, soft skills, and domain expectations exactly as expressed.
- Repeated keywords raise review priority only. They do not change Preferred to Required, responsibility to qualification, or inference to hard gate.
- Set `hard_gate=true` only for an explicitly stated blocking qualification, license, work authorization, location, or genuinely non-substitutable condition.
- Separate recruiting-text anomalies: implausible breadth, conflicting levels, copied wording, missing scope, unclear reporting line, stale dates, or contradictions.
- Do not duplicate the full JD; link to `job-description.md`.

## Explicit versus inferred

Explicit analysis preserves source wording. Inference may explain likely business context or validation expectations, but it must retain basis, source, uncertainty, and confidence. Company/role-family inference cannot become a company-specific hard gate. Company research may shape context but never proves candidate capability.

## Application constraints

Extract location, work mode, language, education, certificate/license, visa/work authorization, travel, start date, and salary constraints into the independent constraint model. Use only `satisfied`, `unsatisfied`, `unknown`, or `not_applicable`; never use role match states for them. Other skills cannot average away an unsatisfied hard constraint. Unknown hard constraints remain pending information.

## Tier behavior

Tier A supports a complete explicit requirement set and coverage denominator. Tier B preserves known explicit items and clearly labeled inferences but leaves complete explicit coverage null. Tier C uses role-family expectations only as a lower-confidence baseline. Tier D performs no role-level requirement analysis until a direction is chosen.
