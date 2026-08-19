# Privacy and Data Handling Policy

Apply least exposure at discovery, retrieval, reasoning, output, logging, and cleanup.

## Source isolation

The career repository is read-only runtime input. Do not vendor, package, fixture, publish, or copy it into this project. Generated text and analysis never write back to `personal-data/`; a verified new real-world artifact must be intentionally recorded by the source owner before it can become evidence.

Keep output and persistent metadata outside the source root. Canonicalize source paths, reject traversal, and do not follow symlinks outside the configured root.

## Persistence allowlist

Persistent navigation indexes may store only source-relative path/ID, source hash, title, heading/anchor, document domain, and internal links. They must never store section bodies, snippets, personal facts, contact details, derived claims, prompts, F6/P3 content, secrets, credentials, private URLs, or internal addresses.

Source bodies may exist only in process memory for the minimum necessary analysis. Filter F6, P3, secrets, credentials, customer/internal details, and prohibited content before any model context. Do not spill them to cache, log, trace, temporary prompt file, workspace, or error report. Dispose of bodies when the process exits.

## Output permission and audience

Directories containing personal data use `0700`; files use `0600`. Refuse output paths inside the source, shared/public paths without explicit safe handling, or existing runs that would be overwritten without confirmation.

P0 is eligible after evidence checks. P1 permits safe summaries. P2 requires `targeted_application`, an exact intended audience/purpose, and confirmation. P3 and F6 never enter any persisted or model-visible channel. Public output excludes P2 and normally phone information.

## Minimize visible and audit data

The visible resume contains only role-relevant, authorized contact and evidence-backed facts. Remove credentials, internal hosts, customer data, private logs/repositories, proprietary implementation detail, and private source paths. Private provenance may use source-relative owning paths and hashes but not copied source bodies.

Errors and validation reports identify claim IDs, paths, checks, and reasons without echoing sensitive text. Do not emit raw JD or personal sections in logs. Never use real personal data in packaged examples, tests, fixtures, or evaluation material.

## Final privacy checks

Verify output location and modes; audience-compatible P level; absence of F4-F6/P3; no secrets or internal identifiers; appropriate contact fields; provenance without body duplication; metadata-only caches; and no retained temporary body copies.
