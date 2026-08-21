export const RESUME_HELP_TOPICS = [
  "overview",
  "init",
  "discover",
  "analyze",
  "generate",
  "audit",
  "status",
  "workflow",
  "privacy",
  "tools",
  "troubleshooting",
] as const;

export type ResumeHelpTopic = (typeof RESUME_HELP_TOPICS)[number];

export interface ResumeHelpCompletion {
  readonly value: string;
  readonly label: string;
  readonly description: string;
}

const HELP_ALIASES: Readonly<Record<string, ResumeHelpTopic>> = Object.freeze({
  "": "overview",
  help: "overview",
  overview: "overview",
  "-h": "overview",
  "--help": "overview",
  "resume-help": "overview",
  init: "init",
  "resume-init": "init",
  discover: "discover",
  "resume-discover": "discover",
  analyze: "analyze",
  analyse: "analyze",
  "resume-analyze": "analyze",
  generate: "generate",
  "resume-generate": "generate",
  audit: "audit",
  "resume-audit": "audit",
  status: "status",
  "resume-status": "status",
  workflow: "workflow",
  privacy: "privacy",
  tools: "tools",
  troubleshooting: "troubleshooting",
  troubleshoot: "troubleshooting",
});

const TOPIC_DESCRIPTIONS: Readonly<Record<ResumeHelpTopic, string>> = Object.freeze({
  overview: "Command index and quick start",
  init: "Run initialization and reviewed-semantic authorization",
  discover: "Metadata-only source discovery",
  analyze: "Independent role and evidence analysis",
  generate: "Locked-claim composition and rendering",
  audit: "Manifest PDF and retained-session audit",
  status: "Private run and manifest status",
  workflow: "Receipt-driven end-to-end state machine",
  privacy: "Metadata-only and reviewed-semantic modes",
  tools: "Nine deterministic Plugin tools",
  troubleshooting: "Common safe failures and prerequisites",
});

const TOPIC_TEXT: Readonly<Record<ResumeHelpTopic, readonly string[]>> = Object.freeze({
  overview: Object.freeze([
    "China Targeted Resume Plugin",
    "",
    "Usage: /resume-help [topic]",
    "Topics: init, discover, analyze, generate, audit, status, workflow, privacy, tools, troubleshooting",
    "",
    "Quick start:",
    "  1. /resume-init application-2026",
    "  2. /resume-discover /absolute/path/to/career-source",
    "  3. /resume-analyze application-2026",
    "  4. /resume-generate application-2026",
    "  5. /resume-audit /absolute/path/to/run/resume-variants.json",
    "  6. /resume-status application-2026",
    "",
    "Default mode is metadata-only. Commands seed the bundled Skill and OMP task fan-out; deterministic tools still validate, lock, compose, render, and inspect every claim and variant.",
    "Use /resume-help privacy before enabling reviewed-semantic mode.",
  ]),
  init: Object.freeze([
    "/resume-init [run-id] [--reviewed-semantic]",
    "",
    "Creates or resets a private Plugin run. Without --reviewed-semantic, only metadata and deterministic extractive materialization are allowed.",
    "",
    "Examples:",
    "  /resume-init application-2026",
    "  /resume-init application-2026 --reviewed-semantic",
    "",
    "Reviewed-semantic setup interactively records the exact main and task provider/model/locality, categories, minimum slices, consumers, purposes, OMP JSONL path, permissions, owner, and retention limits. Authorization fails closed unless the session directory and files satisfy the private-storage gate.",
  ]),
  discover: Object.freeze([
    "/resume-discover SOURCE_ROOT",
    "",
    "Runs fence-aware, ancestry-aware metadata discovery, then delegates semantic navigation mapping to the bundled source-mapper through OMP's built-in task runtime.",
    "",
    "Example:",
    "  /resume-discover /home/user/career-source",
    "",
    "Discovery returns paths, hashes, spans, headings, duplicate identities, structural flags, and effective policy. It does not expose source bodies or approve evidence.",
  ]),
  analyze: Object.freeze([
    "/resume-analyze [run-id]",
    "",
    "Starts independent role, requirement, evidence, contribution/metric, and privacy analysis for the active or named run. Requirement decisions finalize role IR separately; full claim-review wrappers go unchanged to the claim locker.",
    "",
    "Examples:",
    "  /resume-analyze",
    "  /resume-analyze application-2026",
    "",
    "Hard disagreement, missing authorization, unsupported evidence, non-candidate ownership, F3-F6, P3, or unresolved extractive questions stop locking.",
  ]),
  generate: Object.freeze([
    "/resume-generate [run-id]",
    "",
    "Continues only after a same-run evidence receipt and approval receipt exist. It verifies exact approved text and claim placements, composes the default recruiter and technical variants, renders manifest artifacts, and never treats this command as user approval.",
    "",
    "Examples:",
    "  /resume-generate",
    "  /resume-generate application-2026",
    "",
    "The optional extended profile is controlled by the request's include_extended_profile flag. resume-variants.json is always the authoritative artifact list.",
  ]),
  audit: Object.freeze([
    "/resume-audit RESUME_VARIANTS_JSON",
    "",
    "Reads one private resume-variants.json, inspects every listed PDF against its ResumeDocument contract, and audits reviewed-semantic OMP session retention without returning source bodies or private paths in status output.",
    "",
    "Example:",
    "  /resume-audit /absolute/path/to/run/resume-variants.json",
    "",
    "PDF success does not override audit_success=false. Underfill, missing verified fields, content failures, weak session storage, out-of-scope slices, or incomplete receipt proof remain visible failures.",
  ]),
  status: Object.freeze([
    "/resume-status [run-id|RESUME_VARIANTS_JSON]",
    "",
    "Shows the active or selected run's metadata-only privacy summary, completed tools, source/evidence/approval receipts, confirmation count, manifest status, and path-free retained-session audit summary.",
    "",
    "Examples:",
    "  /resume-status",
    "  /resume-status application-2026",
    "  /resume-status /absolute/path/to/run/resume-variants.json",
    "",
    "Status never returns source bodies, exact private slices, prompt transcripts, or session paths.",
  ]),
  workflow: Object.freeze([
    "Receipt-driven workflow",
    "",
    "  /resume-init",
    "    -> resume_discover_structure",
    "    -> resume_validate_source_map (source-map receipt)",
    "    -> source mapping and independent task reviewers",
    "    -> resume_validate_role_ir / resume_validate_evidence_ir (evidence receipt)",
    "    -> resume_lock_approved_claims (approval receipt)",
    "    -> resume_compose_variants",
    "    -> resume_render_variants",
    "    -> resume_inspect_variants",
    "    -> /resume-audit resume-variants.json",
    "",
    "Runtime-held evidence, review, approval, and confirmation bodies are referenced by same-run digests. Do not resend or reconstruct them in compose requests.",
  ]),
  privacy: Object.freeze([
    "Privacy modes",
    "",
    "metadata-only (default): models receive IDs, paths, hashes, spans, headings, structural flags, policy, summaries, and confirmation questions; source bodies stay out of prompts and session results.",
    "",
    "reviewed-semantic: /resume-init RUN --reviewed-semantic requests explicit per-run authorization for exact source slices and exact consumers. Contacts, credentials, whole repositories, F6/P3 bodies, and advisor raw access remain forbidden.",
    "",
    "Before authorization, OMP session storage must be owner-only: directories 0700-equivalent and files 0600-equivalent. Task/advisor JSONL and Markdown are retained and recursively audited. Cleanup is reported only when it is actually supported and verified.",
  ]),
  tools: Object.freeze([
    "Deterministic tools",
    "",
    "Source: resume_discover_structure, resume_read_source_slice, resume_validate_source_map",
    "IR: resume_validate_role_ir, resume_validate_evidence_ir, resume_lock_approved_claims",
    "Artifacts: resume_compose_variants, resume_render_variants, resume_inspect_variants",
    "",
    "Humans normally use /resume-* commands. The bundled Skill calls tools in receipt order. Tools fail explicitly; there is no silent alternate backend or task-runtime replacement.",
  ]),
  troubleshooting: Object.freeze([
    "Troubleshooting",
    "",
    "No claim-lock result: finish evidence validation and independent reviews before /resume-generate.",
    "SOURCE_POLICY_REQUIRED or unrelated-slice: request the exact parser-owned block and match the authorized category, consumer, and purpose.",
    "Weak OMP session tree: configure owner-only 0700 directories and 0600 files; the Plugin does not chmod OMP-owned storage.",
    "Python bridge unavailable: install uv and Python >=3.14, provision the locked Plugin environment, then install Playwright Chromium and a supported CJK font for rendering.",
    "audit_success=false: inspect each variant's validation/audit artifact. PDF success or file existence is not content acceptance.",
    "Underfilled technical variant: add only verified relevant evidence; never pad with invented claims.",
    "",
    "Detailed guide: README.md or README.zh_CN.md in the Plugin package.",
  ]),
});

function normalizeTopic(raw: string): string {
  return raw.trim().toLowerCase().replace(/^\//, "");
}

export function resolveResumeHelpTopic(raw: string): ResumeHelpTopic | undefined {
  const normalized = normalizeTopic(raw);
  if (normalized.includes(" ")) return undefined;
  return HELP_ALIASES[normalized];
}

export function isResumeHelpRequest(raw: string): boolean {
  const normalized = normalizeTopic(raw);
  return normalized === "help" || normalized === "-h" || normalized === "--help";
}

export function resumeHelpText(topic: ResumeHelpTopic): string {
  return TOPIC_TEXT[topic].join("\n");
}

export function resumeHelpError(raw: string): string {
  const topic = raw.trim() || "<empty>";
  return `Unknown help topic ${JSON.stringify(topic)}. Use /resume-help or one of: ${RESUME_HELP_TOPICS.slice(1).join(", ")}`;
}

export function resumeHelpCompletions(argumentPrefix: string): ResumeHelpCompletion[] | null {
  const normalized = normalizeTopic(argumentPrefix);
  if (normalized.includes(" ")) return null;
  const matches = RESUME_HELP_TOPICS.filter((topic) => (
    topic !== "overview" && (normalized.length === 0 || topic.startsWith(normalized))
  ));
  return matches.map((topic) => ({
    value: topic,
    label: topic,
    description: TOPIC_DESCRIPTIONS[topic],
  }));
}
