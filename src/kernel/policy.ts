import { validateSchemaDocument } from "./schema.ts";

export type FactPolicy = "F1" | "F2" | "F3" | "F4" | "F5" | "F6";
export type DisclosurePolicy = "P0" | "P1" | "P2" | "P3";
export type OutputMode = "targeted_application" | "public_portfolio" | "master_resume";
export type ProposalDomain = "role" | "company" | "roadmap" | "evidence" | "job-description" | "personal";
export type ProposalBoundary = "role-input" | "evidence-input";

export interface PolicyDecision {
  readonly allowed_as_candidate: boolean;
  readonly allowed_in_output: boolean;
  readonly confirmation_required: boolean;
  readonly current_verification_required: boolean;
  readonly reason_codes: readonly string[];
  readonly record: Readonly<Record<string, unknown>> | null;
}

export interface EffectivePolicyInput {
  readonly document_fact_policy?: FactPolicy | null;
  readonly document_disclosure_policy?: DisclosurePolicy | null;
  readonly ancestor_fact_policy?: FactPolicy | null;
  readonly ancestor_disclosure_policy?: DisclosurePolicy | null;
  readonly ancestor_fact_policies?: readonly (FactPolicy | null)[];
  readonly ancestor_disclosure_policies?: readonly (DisclosurePolicy | null)[];
  readonly local_fact_policy?: FactPolicy | null;
  readonly local_disclosure_policy?: DisclosurePolicy | null;
  readonly structural_flags?: Readonly<Record<string, unknown>>;
  readonly output_mode?: OutputMode;
  readonly p2_confirmed?: boolean;
}

export interface EffectivePolicyDecision {
  readonly effective_fact_policy: FactPolicy;
  readonly effective_disclosure_policy: DisclosurePolicy;
  readonly blocked: boolean;
  readonly decision: "allowed" | "denied" | "needs_confirmation";
  readonly user_confirmation_required: boolean;
  readonly blocking_reasons: readonly string[];
}

export interface RunRequest {
  readonly schema_version: number;
  readonly source_root: string;
  readonly source_adapter: string;
  readonly company_ref: string | Readonly<Record<string, unknown>> | null;
  readonly role_ref: string | Readonly<Record<string, unknown>> | null;
  readonly jd: Readonly<{ text: string | null; url: string | null; file: string | null }>;
  readonly application_constraints: Readonly<Record<string, unknown>> | readonly Readonly<Record<string, unknown>>[];
  readonly output_mode: OutputMode;
  readonly language: string;
  readonly include_extended_profile: boolean;
  readonly template: "ats-simple" | "human-readable";
  readonly persist_role_research: boolean;
  readonly export_roadmap_handoff: boolean;
  readonly refresh_external_sources: boolean;
  readonly output_root: string;
}

export interface ResumeVariantContract {
  readonly variant: "recruiter-one-page" | "technical-two-page" | "extended-three-page";
  readonly base_name: "resume-recruiter-1p" | "resume-technical-2p" | "technical-profile-3p";
  readonly target_pages: 1 | 2 | 3;
  readonly artifacts: Readonly<{
    document: string;
    provenance: string;
    validation: string;
    audit: string;
    markdown: string;
    ats_text: string;
    html: string;
    pdf: string;
  }>;
}

export class PolicyValidationError extends Error {
  readonly code = "POLICY_VALIDATION_FAILED";

  constructor(message: string) {
    super(message);
    this.name = "PolicyValidationError";
  }
}

const FACT_RANK: Readonly<Record<FactPolicy, number>> = Object.freeze({
  F1: 1,
  F2: 2,
  F3: 3,
  F4: 4,
  F5: 5,
  F6: 6,
});
const DISCLOSURE_RANK: Readonly<Record<DisclosurePolicy, number>> = Object.freeze({
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
});
const FACT_POLICIES: readonly FactPolicy[] = Object.freeze(["F1", "F2", "F3", "F4", "F5", "F6"]);
const DISCLOSURE_POLICIES: readonly DisclosurePolicy[] = Object.freeze(["P0", "P1", "P2", "P3"]);
const OUTPUT_MODES = Object.freeze(["targeted_application", "public_portfolio", "master_resume"] as const);
const ROLE_INPUT_DOMAINS: readonly ProposalDomain[] = Object.freeze(["role", "job-description"]);
const EVIDENCE_INPUT_DOMAINS: readonly ProposalDomain[] = Object.freeze(["evidence"]);
const ALLOWED_DOMAINS: Readonly<Record<ProposalBoundary, readonly ProposalDomain[]>> = Object.freeze({
  "role-input": ROLE_INPUT_DOMAINS,
  "evidence-input": EVIDENCE_INPUT_DOMAINS,
});
const STRUCTURAL_BLOCK_FLAGS = Object.freeze([
  "inside_fence",
  "inside_blockquote",
  "inside_html",
  "is_example",
  "is_template",
  "is_quoted",
  "negative_instruction",
  "secret_path",
  "secret_content",
  "malformed",
] as const);
const FACT_PROSE: readonly (readonly [FactPolicy, readonly string[]])[] = Object.freeze([
  ["F6", Object.freeze([
    "strictly confidential", "高度敏感", "绝密", "不得读取", "do not ingest",
    "内部凭据", "内部地址", "内部仓库", "客户数据", "customer data", "proprietary data",
  ])],
  ["F5", Object.freeze(["待确认", "需要确认", "待本人确认", "unconfirmed", "needs confirmation", "to confirm", "unknown"])],
  ["F4", Object.freeze(["合理推断", "推测", "可能", "据说", "assumed", "inferred", "possibly"])],
  ["F3", Object.freeze([
    "尚未复核", "待复核", "缺少最近核验", "未作最近核验",
    "not recently verified", "recent verification missing", "verification required", "reverify",
  ])],
  ["F2", Object.freeze(["有限口径", "约", "阶段记录", "limited scope", "approximate"])],
  ["F1", Object.freeze([
    "明确事实", "来自原始综合资料", "本人确认", "可公开核验", "公开事实",
    "verified fact", "confirmed by the candidate", "source-backed fact", "publicly verified",
  ])],
]);
const DISCLOSURE_PROSE: readonly (readonly [DisclosurePolicy, readonly string[]])[] = Object.freeze([
  ["P3", Object.freeze([
    "不得披露", "不得使用", "禁止输出", "内部标识", "内部数据", "内部秘密",
    "do not disclose", "never disclose", "private only", "internal identifier", "internal data",
  ])],
  ["P2", Object.freeze([
    "仅限求职", "仅限定向投递", "仅限面试", "定向材料", "targeted application only",
    "application only", "interview only",
  ])],
  ["P1", Object.freeze([
    "可公开概述", "公司角色", "岗位职责", "通用技术栈", "抽象架构",
    "limited disclosure", "company role", "general stack", "abstract architecture",
  ])],
  ["P0", Object.freeze([
    "公开链接", "开源链接", "已核验公开事实", "可公开引用",
    "public link", "open-source link", "verified public fact", "publishable link",
  ])],
]);
const SENSITIVE_CONTENT = /(?:身份证|护照|银行卡|银行账户|家庭住址|内部地址|内部仓库|客户数据|客户名称|薪资|工资|电话(?:号码)?|手机号|(?:内部|生产|真实)(?:凭据|密钥)|personal\s+(?:id|address|phone)|passport|bank\s+account|customer\s+data|internal\s+(?:address|identifier|repository)|salary|compensation|credential\s*[:=]|password\s*[:=]|api\s+key\s*[:=]|access\s+token\s*[:=]|private\s+key\s*[:=])/iu;

function objectValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function field(value: unknown, names: readonly string[], fallback?: unknown): unknown {
  const data = objectValue(value);
  for (const name of names) {
    if (data[name] !== undefined && data[name] !== null) return data[name];
  }
  return fallback;
}


function mostRestrictiveFact(values: readonly (FactPolicy | null | undefined)[]): FactPolicy {
  const present: FactPolicy[] = [];
  for (const value of values) {
    if (value === null || value === undefined) continue;
    switch (value) {
      case "F1":
      case "F2":
      case "F3":
      case "F4":
      case "F5":
      case "F6":
        present.push(value);
        break;
      default:
        throw new PolicyValidationError(`unknown fact policy ${JSON.stringify(value)}`);
    }
  }
  const [first, ...rest] = present;
  if (first === undefined) return "F5";
  let result = first;
  for (const value of rest) {
    if (FACT_RANK[value] > FACT_RANK[result]) result = value;
  }
  return result;
}

function mostRestrictiveDisclosure(values: readonly (DisclosurePolicy | null | undefined)[]): DisclosurePolicy {
  const present: DisclosurePolicy[] = [];
  for (const value of values) {
    if (value === null || value === undefined) continue;
    switch (value) {
      case "P0":
      case "P1":
      case "P2":
      case "P3":
        present.push(value);
        break;
      default:
        throw new PolicyValidationError(`unknown disclosure policy ${JSON.stringify(value)}`);
    }
  }
  const [first, ...rest] = present;
  if (first === undefined) return "P3";
  let result = first;
  for (const value of rest) {
    if (DISCLOSURE_RANK[value] > DISCLOSURE_RANK[result]) result = value;
  }
  return result;
}

export function parsePolicyMarkers(
  text: unknown,
  defaults: Readonly<{ fact?: FactPolicy; disclosure?: DisclosurePolicy }> = {},
): Readonly<{ fact: FactPolicy; disclosure: DisclosurePolicy }> {
  const defaultFact = mostRestrictiveFact([defaults.fact]);
  const defaultDisclosure = mostRestrictiveDisclosure([defaults.disclosure]);
  if (typeof text !== "string") return Object.freeze({ fact: defaultFact, disclosure: defaultDisclosure });
  const facts = new Set<FactPolicy>();
  const disclosures = new Set<DisclosurePolicy>();
  for (const match of text.matchAll(/(?<![A-Z0-9])F([1-6])(?![A-Z0-9])/giu)) {
    switch (match[1]) {
      case "1": facts.add("F1"); break;
      case "2": facts.add("F2"); break;
      case "3": facts.add("F3"); break;
      case "4": facts.add("F4"); break;
      case "5": facts.add("F5"); break;
      case "6": facts.add("F6"); break;
    }
  }
  for (const match of text.matchAll(/(?<![A-Z0-9])P([0-3])(?![A-Z0-9])/giu)) {
    switch (match[1]) {
      case "0": disclosures.add("P0"); break;
      case "1": disclosures.add("P1"); break;
      case "2": disclosures.add("P2"); break;
      case "3": disclosures.add("P3"); break;
    }
  }
  const lowered = text.toLocaleLowerCase("und");
  if (facts.size === 0) {
    for (const [marker, phrases] of FACT_PROSE) {
      if (phrases.some((phrase) => lowered.includes(phrase.toLocaleLowerCase("und")))) facts.add(marker);
    }
  }
  if (disclosures.size === 0) {
    for (const [marker, phrases] of DISCLOSURE_PROSE) {
      if (phrases.some((phrase) => lowered.includes(phrase.toLocaleLowerCase("und")))) disclosures.add(marker);
    }
  }
  return Object.freeze({
    fact: facts.size === 0 ? defaultFact : mostRestrictiveFact([...facts]),
    disclosure: disclosures.size === 0 ? defaultDisclosure : mostRestrictiveDisclosure([...disclosures]),
  });
}

export function detectSensitiveContent(text: unknown): boolean {
  return typeof text === "string" && SENSITIVE_CONTENT.test(text);
}

export function resolveEffectivePolicy(input: EffectivePolicyInput): EffectivePolicyDecision {
  const effectiveFact = mostRestrictiveFact([
    input.document_fact_policy,
    input.ancestor_fact_policy,
    ...(input.ancestor_fact_policies ?? []),
    input.local_fact_policy,
  ]);
  const effectiveDisclosure = mostRestrictiveDisclosure([
    input.document_disclosure_policy,
    input.ancestor_disclosure_policy,
    ...(input.ancestor_disclosure_policies ?? []),
    input.local_disclosure_policy,
  ]);
  const flags = objectValue(input.structural_flags);
  const reasons: string[] = STRUCTURAL_BLOCK_FLAGS.filter((name) => flags[name] === true);
  if (effectiveFact === "F6") reasons.push("fact_policy:F6");
  if (effectiveDisclosure === "P3") reasons.push("disclosure_policy:P3");
  let decision: EffectivePolicyDecision["decision"] = reasons.length > 0 ? "denied" : "allowed";
  let confirmationRequired = false;
  if (decision === "allowed" && effectiveDisclosure === "P2") {
    if (input.output_mode !== undefined && input.output_mode !== "targeted_application") {
      reasons.push("targeted_application_only");
      decision = "denied";
    } else if (input.p2_confirmed !== true) {
      reasons.push("p2_permission_unknown");
      confirmationRequired = true;
      decision = "needs_confirmation";
    }
  }
  return Object.freeze({
    effective_fact_policy: effectiveFact,
    effective_disclosure_policy: effectiveDisclosure,
    blocked: decision !== "allowed",
    decision,
    user_confirmation_required: confirmationRequired,
    blocking_reasons: Object.freeze([...new Set(reasons)]),
  });
}
export function evaluatePolicy(input: EffectivePolicyInput): EffectivePolicyDecision {
  return resolveEffectivePolicy(input);
}


export function assertProposalDomain(domain: unknown, boundary: ProposalBoundary): ProposalDomain {
  let normalized: ProposalDomain;
  switch (domain) {
    case "role":
    case "company":
    case "roadmap":
    case "evidence":
    case "job-description":
    case "personal":
      normalized = domain;
      break;
    default:
      throw new PolicyValidationError(`unknown proposal domain ${JSON.stringify(domain)}`);
  }
  if (!ALLOWED_DOMAINS[boundary].includes(normalized)) {
    throw new PolicyValidationError(
      `${boundary} proposal has forbidden domain ${JSON.stringify(normalized)}`,
    );
  }
  return normalized;
}

export function assertSeparatedDomains(
  proposals: readonly unknown[],
  boundary: ProposalBoundary,
): void {
  proposals.forEach((proposal, index) => {
    const domain = field(proposal, ["domain"]);
    try {
      assertProposalDomain(domain, boundary);
    } catch (error) {
      if (error instanceof PolicyValidationError) {
        throw new PolicyValidationError(`${boundary} proposal at index ${index}: ${error.message}`);
      }
      throw error;
    }
  });
}

function freshnessFields(value: unknown): Readonly<{ stale: unknown; verified: unknown; expires: unknown }> {
  let stale = field(value, ["is_stale", "stale"]);
  let verified = field(value, ["verified_at", "last_verified_at", "as_of"]);
  let expires = field(value, ["expires_at", "valid_until", "stale_after"]);
  const freshness = field(value, ["freshness"]);
  if (freshness !== undefined && freshness !== null) {
    stale = field(freshness, ["stale"], stale);
    verified = field(freshness, ["checked_at"], verified);
    expires = field(freshness, ["expires_at"], expires);
  }
  return Object.freeze({ stale, verified, expires });
}

function staleAt(value: unknown, now: Date | string | undefined): boolean {
  const freshness = freshnessFields(value);
  if (freshness.stale !== undefined && freshness.stale !== null) return Boolean(freshness.stale);
  if (freshness.verified === undefined || freshness.verified === null) return true;
  if (freshness.expires === undefined || freshness.expires === null) return false;
  const current = now instanceof Date ? now : now === undefined ? new Date() : new Date(now);
  const expires = new Date(String(freshness.expires));
  if (Number.isNaN(current.getTime()) || Number.isNaN(expires.getTime())) return true;
  return current.getTime() > expires.getTime();
}

export function applyEvidencePolicy(
  value: unknown,
  mode: OutputMode | string,
  options: Readonly<{ now?: Date | string }> = {},
): PolicyDecision {
  const fact = String(field(value, ["fact_state", "fact", "fact_level"], "F5")).toUpperCase();
  const disclosure = String(field(value, ["disclosure_level", "disclosure", "privacy_level"], "P3")).toUpperCase();
  const modeValue = String(mode).toLowerCase();
  const reasons: string[] = [];
  let candidate = true;
  let output = true;
  let confirmation = false;
  let currentVerification = false;

  if (fact === "F6" || disclosure === "P3") {
    candidate = false;
    output = false;
    reasons.push("excluded_from_processing");
  }
  const content = ["proposed_claim", "safe_claim", "rendered_claim", "body", "snippet"]
    .map((name) => String(field(value, [name], "") ?? ""))
    .join(" ");
  if (detectSensitiveContent(content)) {
    candidate = false;
    output = false;
    reasons.push("sensitive_content_detected");
  }
  if (fact === "F4" || fact === "F5") {
    output = false;
    confirmation = fact === "F4";
    reasons.push(fact === "F4" ? "unconfirmed_fact" : "unsupported_fact");
  }
  if (disclosure === "P2" && modeValue !== "targeted_application") {
    output = false;
    reasons.push("targeted_application_only");
  }
  if (fact === "F3") {
    currentVerification = true;
    const freshness = freshnessFields(value);
    if (staleAt(value, options.now) || freshness.verified === undefined || freshness.verified === null) {
      output = false;
      confirmation = true;
      reasons.push("current_verification_required");
    }
  }
  if (!FACT_POLICIES.includes(fact as FactPolicy)) {
    candidate = false;
    output = false;
    reasons.push("unknown_fact_state");
  }
  if (!DISCLOSURE_POLICIES.includes(disclosure as DisclosurePolicy)) {
    candidate = false;
    output = false;
    reasons.push("unknown_disclosure_level");
  }

  return Object.freeze({
    allowed_as_candidate: candidate,
    allowed_in_output: output,
    confirmation_required: confirmation,
    current_verification_required: currentVerification,
    reason_codes: Object.freeze([...new Set(reasons)]),
    record: candidate ? Object.freeze({ ...objectValue(value) }) : null,
  });
}

export function validateRequestConstraints(value: unknown): RunRequest {
  const request = validateSchemaDocument(value, "request") as unknown as Record<string, unknown>;
  const jd = objectValue(request.jd);
  const constraints = request.application_constraints ?? {};
  return Object.freeze({
    schema_version: (request.schema_version ?? 1) as number,
    source_root: request.source_root as string,
    source_adapter: (request.source_adapter ?? "markdown-career-v1") as string,
    company_ref: (request.company_ref ?? null) as RunRequest["company_ref"],
    role_ref: (request.role_ref ?? null) as RunRequest["role_ref"],
    jd: Object.freeze({
      text: (jd.text ?? null) as string | null,
      url: (jd.url ?? null) as string | null,
      file: (jd.file ?? null) as string | null,
    }),
    application_constraints: constraints as RunRequest["application_constraints"],
    output_mode: (request.output_mode ?? "targeted_application") as OutputMode,
    language: (request.language ?? "zh-CN") as string,
    include_extended_profile: (request.include_extended_profile ?? false) as boolean,
    template: (request.template ?? "ats-simple") as RunRequest["template"],
    persist_role_research: (request.persist_role_research ?? false) as boolean,
    export_roadmap_handoff: (request.export_roadmap_handoff ?? false) as boolean,
    refresh_external_sources: (request.refresh_external_sources ?? false) as boolean,
    output_root: request.output_root as string,
  });
}

const VARIANT_CONTRACTS = Object.freeze([
  Object.freeze({ variant: "recruiter-one-page", base_name: "resume-recruiter-1p", target_pages: 1 }),
  Object.freeze({ variant: "technical-two-page", base_name: "resume-technical-2p", target_pages: 2 }),
  Object.freeze({ variant: "extended-three-page", base_name: "technical-profile-3p", target_pages: 3 }),
] as const);

function variantWithArtifacts(contract: (typeof VARIANT_CONTRACTS)[number]): ResumeVariantContract {
  const base = contract.base_name;
  return Object.freeze({
    ...contract,
    artifacts: Object.freeze({
      document: `${base}.document.json`,
      provenance: `${base}.provenance.json`,
      validation: `${base}.validation.json`,
      audit: `${base}.audit.md`,
      markdown: `${base}.md`,
      ats_text: `${base}.txt`,
      html: `${base}.html`,
      pdf: `${base}.pdf`,
    }),
  });
}

export function validateResumeVariantsManifest(value: unknown): Readonly<Record<string, unknown>> {
  return validateSchemaDocument(value, "resume-variants");
}

export function expectedResumeVariants(requestValue: unknown): readonly ResumeVariantContract[] {
  const request = validateRequestConstraints(requestValue);
  const count = request.include_extended_profile ? 3 : 2;
  return Object.freeze(VARIANT_CONTRACTS.slice(0, count).map(variantWithArtifacts));
}

export function assertVariantConstraints(requestValue: unknown, variants: readonly unknown[]): void {
  const expected = expectedResumeVariants(requestValue);
  if (variants.length !== expected.length) {
    throw new PolicyValidationError(`resume variant selection must contain exactly ${expected.length} ordered variants`);
  }
  expected.forEach((contract, index) => {
    const value = variants[index];
    const record = objectValue(value);
    const variant = typeof value === "string" ? value : record.variant;
    if (variant !== contract.variant) {
      throw new PolicyValidationError(
        `resume variant at index ${index} must be ${contract.variant}, not ${String(variant)}`,
      );
    }
    if (typeof value !== "string") {
      if (record.base_name !== undefined && record.base_name !== contract.base_name) {
        throw new PolicyValidationError(`resume variant ${contract.variant} has a non-canonical base_name`);
      }
      if (record.target_pages !== undefined && record.target_pages !== contract.target_pages) {
        throw new PolicyValidationError(`resume variant ${contract.variant} has a non-canonical target_pages value`);
      }
    }
  });
}
