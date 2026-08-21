import type {
  RunPrivacyState,
  SourceSliceAllowed,
  SourceSlicePrefilterResult,
  SourceSliceRequest,
  SourceSliceReader,
  SourceSliceDenied,
  CanonicalDisclosureConsumer,
} from "./types";
import {
  SourceSlicePolicyError,
  canonicalConsumer,
  containsContact,
  containsCredential,
  containsF6P3,
  hasForbiddenSentinel,
  isLikelyWholeRepository,
  isSliceWithin,
} from "./guards";
import { disclosureFor } from "./state";

export const DEFAULT_MAX_SOURCE_SLICE_BYTES = 16 * 1024;
export const MAX_SOURCE_SLICE_BYTES = 64 * 1024;

const CONTACT_PATH = /(?:^|[/_.-])(?:contacts?|contact[-_. ]?info|address[-_. ]?book|phone|email|e[-_]?mail|linkedin)(?:$|[/_.-])/i;
const CREDENTIAL_PATH = /(?:^|[/_.-])(?:credentials?|passwords?|secrets?|tokens?|api[-_]?keys?|private(?:[-_. ]?(?:keys?|data|info|notes?))?|access[-_]?keys?|sensitive|\.env|id[_-]?rsa|.*\.pem)(?:$|[/_.-])/i;
const POLICY_PATH = /(?:^|[/_.-])(?:f6|p3|f6[-_. ]?p3|restricted|private[-_. ]?policy)(?:$|[/_.-])/i;

function deny(
  request: SourceSliceRequest,
  code: SourceSliceDenied["code"],
  reason: string,
): SourceSliceDenied {
  return Object.freeze({
    ok: false,
    ...(request.requestId === undefined ? {} : { requestId: request.requestId }),
    code,
    reason,
  });
}

function bytesOf(content: string | Uint8Array): number {
  if (typeof content === "string") return new TextEncoder().encode(content).byteLength;
  return content.byteLength;
}

function asText(content: string | Uint8Array): string {
  return typeof content === "string" ? content : new TextDecoder().decode(content);
}

function boundedPath(path: string): string {
  const normalized = path.replaceAll("\\", "/").trim();
  if (
    !normalized ||
    normalized === "." ||
    normalized === "/" ||
    normalized === ".." ||
    normalized === "**" ||
    normalized === "*" ||
    /\s{2,}/.test(normalized) ||
    (/\s/.test(normalized) && !normalized.includes("/")) ||
    normalized.endsWith("/") ||
    normalized.includes("//") ||
    normalized.split("/").some((part) => part === "..") ||
    /[*?{}[\]]/.test(normalized)
  ) {
    throw new SourceSlicePolicyError("invalid-path", "Source slice path must name a bounded file");
  }
  return normalized;
}

function pathWithinRoot(path: string, root: string | undefined): boolean {
  if (!root) return true;
  const normalizedPath = path.replaceAll("\\", "/");
  const normalizedRoot = root.replaceAll("\\", "/").replace(/\/$/, "");
  if (!normalizedRoot) return true;
  if (normalizedPath.startsWith("/") !== normalizedRoot.startsWith("/")) return false;
  const pathParts = normalizedPath.split("/").filter(Boolean);
  const rootParts = normalizedRoot.split("/").filter(Boolean);
  if (rootParts.length > pathParts.length) return false;
  return rootParts.every((part, index) => part === pathParts[index]);
}
function scopePath(path: string, root: string | undefined): string {
  const normalizedPath = path.replaceAll("\\", "/");
  if (!root) return normalizedPath;
  const normalizedRoot = root.replaceAll("\\", "/").replace(/\/$/, "");
  const rootPrefix = `${normalizedRoot}/`;
  if (normalizedPath === normalizedRoot) return "";
  if (normalizedPath.startsWith(rootPrefix)) return normalizedPath.slice(rootPrefix.length);
  return normalizedPath;
}

function validateRange(request: SourceSliceRequest): boolean {
  if (request.startLine === undefined && request.endLine === undefined) return true;
  if (
    request.startLine === undefined ||
    request.endLine === undefined ||
    !Number.isSafeInteger(request.startLine) ||
    !Number.isSafeInteger(request.endLine) ||
    request.startLine < 1 ||
    request.endLine < request.startLine
  ) {
    return false;
  }
  return true;
}

function authorizationAllows(
  state: RunPrivacyState,
  consumer: CanonicalDisclosureConsumer,
  request: SourceSliceRequest,
): boolean {
  if (state.mode !== "reviewed-semantic" || !state.authorization) return false;
  if (!disclosureFor(state, consumer).rawSourceAllowed) return false;
  if (
    request.authorizationId !== undefined &&
    request.authorization_id !== undefined &&
    request.authorizationId !== request.authorization_id
  ) {
    return false;
  }
  const authorizationId = request.authorizationId ?? request.authorization_id;
  if (authorizationId !== state.authorization.authorizationId) return false;
  const identity = state.authorization.consumerIdentities[consumer];
  if (!identity) return false;
  if (
    request.provider !== identity.provider ||
    request.model !== identity.model ||
    request.locality !== identity.locality
  ) {
    return false;
  }
  const category = request.category?.toLowerCase();
  if (consumer === "role-analyst" && (!category || !/(?:jd|role|company|requirement)/.test(category))) return false;
  if (
    consumer === "evidence-reviewer" &&
    (!category || !/(?:evidence|claim|support|requirement)/.test(category))
  ) {
    return false;
  }
  if (
    (consumer === "requirement-reviewer" && (!category || !/(?:jd|role|company|requirement)/.test(category))) ||
    (consumer === "contribution-reviewer" && (!category || !/(?:evidence|claim|support|requirement)/.test(category)))
  ) {
    return false;
  }
  if (consumer === "privacy-reviewer" && (!category || !/(?:policy|evidence|claim|candidate)/.test(category))) return false;
  const categoryAllowed = request.category === undefined || state.authorization.categories.includes(request.category);
  if (!categoryAllowed) return false;
  const scopedRequest = {
    ...request,
    path: scopePath(request.path, request.repositoryRoot),
  };
  return state.authorization.minimumSlices.some((slice) =>
    isSliceWithin(scopedRequest, {
      ...slice,
      path: scopePath(slice.path, request.repositoryRoot),
    }),
  );
}

function policyRejectMetadata(request: SourceSliceRequest): SourceSliceDenied | undefined {
  if (request.blockedByPolicy === true) {
    return deny(request, "forbidden-policy", "Parser-derived policy marks this slice as forbidden");
  }
  const policies = [
    ...(request.effectivePolicy === undefined ? [] : [request.effectivePolicy]),
    ...(request.privacyLevel === undefined ? [] : [request.privacyLevel]),
    ...(request.policy === undefined ? [] : [request.policy]),
    ...(request.ancestorPolicies ?? []),
  ];
  if (policies.some((value) => containsF6P3(value))) {
    return deny(request, "forbidden-policy", "Parser-derived F6/P3 ancestry is forbidden");
  }
  return undefined;
}

function policyRejectPath(request: SourceSliceRequest, path: string): SourceSliceDenied | undefined {
  if (isLikelyWholeRepository(request)) return deny(request, "whole-repository", "Whole-repository disclosure is forbidden");
  if (CONTACT_PATH.test(path)) return deny(request, "contact-path", "Contact-bearing paths are forbidden");
  if (CREDENTIAL_PATH.test(path)) return deny(request, "secret-looking-path", "Secret-looking paths are forbidden");
  if (POLICY_PATH.test(path) || containsF6P3(path)) return deny(request, "forbidden-policy", "F6/P3 policy paths are forbidden");
  if (!pathWithinRoot(path, request.repositoryRoot)) return deny(request, "invalid-path", "Source slice is outside the source root");
  return undefined;
}

function policyRejectContent(request: SourceSliceRequest, content: string): SourceSliceDenied | undefined {
  if (containsF6P3(content)) return deny(request, "forbidden-content", "F6/P3 content is forbidden");
  if (containsCredential(content)) return deny(request, "credential-content", "Credential-like content is forbidden");
  if (containsContact(content)) return deny(request, "contact-content", "Contact-bearing content is forbidden");
  if (hasForbiddenSentinel(content)) return deny(request, "forbidden-content", "Forbidden disclosure sentinel detected");
  return undefined;
}

/**
 * Check a source request before any reader is called.  In metadata-only mode
 * this always denies raw text, including requests carrying no content yet.
 */
export function prefilterSourceSlice(
  state: RunPrivacyState,
  request: SourceSliceRequest,
): SourceSlicePrefilterResult {
  let path: string;
  try {
    path = boundedPath(request.path);
  } catch (error) {
    if (error instanceof SourceSlicePolicyError) return deny(request, "invalid-path", error.message);
    return deny(request, "invalid-path", "Source slice path is invalid");
  }
  const metadataRejection = policyRejectMetadata(request);
  if (metadataRejection) return metadataRejection;
  const pathRejection = policyRejectPath(request, path);
  if (pathRejection) return pathRejection;
  if (!validateRange(request)) return deny(request, "invalid-range", "Source slice line range is invalid");
  if (state.mode === "metadata-only") return deny(request, "metadata-only", "Metadata-only mode never discloses source bodies");
  let consumer: CanonicalDisclosureConsumer;
  try {
    consumer = canonicalConsumer(request.consumer);
  } catch {
    return deny(request, "consumer-forbidden", "Disclosure consumer is not permitted");
  }
  if (!authorizationAllows(state, consumer, request)) {
    return deny(request, state.authorization ? "unrelated-slice" : "missing-authorization", "Slice is outside the authorized minimum scope");
  }
  const identity = state.authorization!.consumerIdentities[consumer];
  if (!identity) return deny(request, "consumer-forbidden", "No provider identity is authorized for this consumer");
  const explicitBytes = request.bytes;
  if (explicitBytes !== undefined && (!Number.isSafeInteger(explicitBytes) || explicitBytes < 0)) {
    return deny(request, "oversize", "Source slice byte count is invalid");
  }
  const maxBytes = Math.min(request.maxBytes ?? DEFAULT_MAX_SOURCE_SLICE_BYTES, MAX_SOURCE_SLICE_BYTES);
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) return deny(request, "oversize", "Source slice byte limit is invalid");
  if (explicitBytes !== undefined && explicitBytes > maxBytes) return deny(request, "oversize", "Source slice exceeds the authorized byte limit");
  const result: SourceSliceAllowed = {
    ok: true,
    authorizationId: state.authorization!.authorizationId,
    provider: identity.provider,
    model: identity.model,
    locality: identity.locality,
    ...(request.requestId === undefined ? {} : { requestId: request.requestId }),
    mode: "reviewed-semantic",
    consumer,
    purpose: request.purpose!,
    path,
    ...(request.startLine === undefined ? {} : { startLine: request.startLine }),
    ...(request.endLine === undefined ? {} : { endLine: request.endLine }),
    ...(request.category === undefined ? {} : { category: request.category }),
    bytes: explicitBytes ?? 0,
  };
  if (request.content !== undefined) {
    const content = asText(request.content);
    const bytes = bytesOf(request.content);
    if (bytes > maxBytes) return deny(request, "oversize", "Source slice exceeds the authorized byte limit");
    const contentRejection = policyRejectContent(request, content);
    if (contentRejection) return contentRejection;
    return Object.freeze({ ...result, bytes, content });
  }
  return Object.freeze(result);
}

/**
 * Read only after path/mode/scope checks.  Content is checked before it is
 * returned to the caller, and denied results never carry the source body.
 */
export async function readAuthorizedSourceSlice(
  state: RunPrivacyState,
  request: SourceSliceRequest,
  reader: SourceSliceReader,
): Promise<SourceSlicePrefilterResult> {
  const beforeRead = prefilterSourceSlice(state, request);
  if (!beforeRead.ok) return beforeRead;
  if (request.content !== undefined) return beforeRead;
  const raw = await reader(request);
  const bytes = bytesOf(raw);
  const withContent = prefilterSourceSlice(state, { ...request, bytes, content: raw });
  if (!withContent.ok) return withContent;
  return withContent;
}

export const canReadSourceSlice = (
  state: RunPrivacyState,
  request: SourceSliceRequest,
): boolean => prefilterSourceSlice(state, request).ok;

export function sourceSliceError(result: SourceSlicePrefilterResult): SourceSlicePolicyError | undefined {
  if (result.ok) return undefined;
  return new SourceSlicePolicyError(result.code, result.reason);
}
