# Evidence and Claim Policy

Apply these gates before a personal fact enters analysis, a prompt, or resume content. The source knowledge base is authoritative; generated text is downstream only.

## Canonical role match states

Serialize exactly one of:

| Value | Meaning |
| --- | --- |
| `已有直接证据` | An owning personal-data section directly supports the requirement. |
| `可迁移经验` | Verified structurally similar experience exists and the transfer is explainable. |
| `有知识无实践` | Knowledge/learning is recorded, but no verified practical project exists. |
| `明确缺口` | Current sources support neither sufficient knowledge nor experience. |
| `待确认` | Role or personal information is insufficient. |

Do not create synonyms, English serialized values, or “partial/weak match.” Positive states require owning source links. Plans, courses, time spent, and confidence never upgrade a state.

## Evidence record

Before selection, bind every candidate claim to evidence ID, requirement IDs, source-relative path, exact section/anchor, source hash, fact state, disclosure level, canonical match state, contribution scope, metric precision, freshness, a bounded safe claim, and forbidden expansions.

## Fact-state gates

- F1: usable after disclosure and contribution checks.
- F2: usable only with original range, approximation, stage, environment, and metric qualifiers.
- F3: revalidate before use; omit or keep audit-only when validation fails.
- F4: exclude from final content and convert to a confirmation question.
- F5: exclude from final content.
- F6: exclude from index, prompt, cache, log, trace, temporary material, and every output.

## Disclosure gates

- P0: allowed in public and targeted modes after fact checks.
- P1: use only a safe overview with proprietary/client/internal detail removed.
- P2: allowed only for a confirmed target and purpose in `targeted_application`; require confirmation before selection.
- P3: exclude from index, prompt, cache, log, trace, temporary material, and every output.

`public_portfolio` permits P0 and safe P1, normally omitting phone details. `targeted_application` may permit confirmed P2. A master resume is private but still does not permit F4-F6 or P3.

## Contribution and metric gates

Preserve contribution strength: support/collaborate < participate < own/implement < drive < lead. Never strengthen a verb for style. “Lead” requires evidence of scoped decision and delivery responsibility. Do not attribute team results solely to an individual.

Metrics retain exact/approximate/range form, unit, date or stage, sample/environment scope, aggregation where known, source, and personal/team boundary. Never turn a stage record into a current production SLA or a historical value into a live one.

## Freshness and selection

Recheck dynamic employment status, city, public links, role-open status, and current metrics. Omit stale facts or ask for confirmation. Rank evidence by requirement importance, strength, directness, recency, verifiability, contribution clarity, disclosure suitability, and page cost—not keyword count.

Every visible factual claim must resolve through provenance to an owning source section. Company research can reorder or contextualize facts but cannot establish them.
