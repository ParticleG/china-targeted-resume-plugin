# Fact Boundaries

## Fact status

- **F1 — Verified:** supported by an owning record and safe to state with its qualifiers.
- **F2 — Strongly supported:** supported by consistent synthetic records but not independently verified.
- **F3 — Self-reported:** may be used conservatively with attribution.
- **F4 — Unverified:** exclude from claims; it may be converted into a clarification question.
- **F5 — Conflicting:** exclude from claims until the conflict is resolved; it may be converted into a question.
- **F6 — Sensitive secret:** never place in prompts, output, indexes, caches, logs, or traces.

## Publicity

- **P0 — Public:** suitable for a public resume.
- **P1 — Generalized:** suitable only after removing unnecessary detail.
- **P2 — Targeted:** may appear only in a targeted resume for the named fictional application.
- **P3 — Secret:** never place in prompts, output, indexes, caches, logs, traces, or temporary workspaces.

Fact and publicity gates are independent. The stricter gate wins.
