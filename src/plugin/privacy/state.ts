import { dirname } from "node:path";
import type {
  CreateRunPrivacyStateInput,
  DisclosurePolicy,
  DisclosureConsumer,
  PrivacyMode,
  PrivacyStatusSummary,
  ReviewedSemanticAuthorization,
  ReviewedSemanticAuthorizationInput,
  RunPrivacyState,
  SessionJsonlObservationInput,
  SourceSliceDescriptor,
  CanonicalDisclosureConsumer,
  ConsumerIdentityMap,
  ConsumerIdentityMapInput,
  ProviderIdentity,
} from "./types";
import {
  PrivacyAuthorizationError,
  assertSafeMetadata,
  canonicalConsumer,
  normalizeMetadataString,
  normalizeRetention,
  normalizeSessionObservation,
  normalizeSessionDirectoryObservation,
  normalizeSliceDescriptor,
  normalizeTimestamp,
  safeRunId,
  safeAuthorizationId,
  hasPrivatePermissions,
} from "./guards";

const DEFAULT_RETENTION = Object.freeze({
  strategy: "not-applicable" as const,
  cleanupSupported: false,
  cleanupLimits: Object.freeze([] as string[]),
  deletionGuarantee: "not-guaranteed" as const,
});

const DISCLOSURE_POLICIES: Readonly<Record<CanonicalDisclosureConsumer, {
  readonly metadata: readonly string[];
  readonly reviewedSemantic: readonly string[];
  readonly alwaysForbidden: readonly string[];
}>> = Object.freeze({
  main: {
    metadata: Object.freeze(["run state", "IDs", "structural metadata", "summaries", "confirmation questions"]),
    reviewedSemantic: Object.freeze(["minimum prefiltered slices needed to coordinate a review"]),
    alwaysForbidden: Object.freeze(["whole repository", "credentials", "F6/P3 bodies"]),
  },
  "source-mapper": {
    metadata: Object.freeze(["structure metadata"]),
    reviewedSemantic: Object.freeze(["requested minimum prefiltered slices"]),
    alwaysForbidden: Object.freeze(["contacts", "unrelated documents", "F6/P3 bodies"]),
  },
  "role-analyst": {
    metadata: Object.freeze(["JD/company structure metadata"]),
    reviewedSemantic: Object.freeze(["minimum JD/company slices"]),
    alwaysForbidden: Object.freeze(["candidate contacts", "unrelated private evidence"]),
  },
  "requirement-reviewer": {
    metadata: Object.freeze(["one requirement", "claim IDs", "validation summaries"]),
    reviewedSemantic: Object.freeze(["minimum JD/company/requirement slices"]),
    alwaysForbidden: Object.freeze(["candidate contacts", "unrelated private evidence", "F6/P3 bodies"]),
  },
  "evidence-reviewer": {
    metadata: Object.freeze(["one requirement", "claim IDs", "validation summaries"]),
    reviewedSemantic: Object.freeze(["one requirement", "one claim", "exact prefiltered slices"]),
    alwaysForbidden: Object.freeze(["unrelated projects", "full profile", "F6/P3 bodies"]),
  },
  "contribution-reviewer": {
    metadata: Object.freeze(["one claim", "metric IDs", "validation summaries"]),
    reviewedSemantic: Object.freeze(["one claim", "exact supporting slices"]),
    alwaysForbidden: Object.freeze(["unrelated projects", "full profile", "F6/P3 bodies"]),
  },
  "privacy-reviewer": {
    metadata: Object.freeze(["policy metadata", "deterministic findings"]),
    reviewedSemantic: Object.freeze(["exact prefiltered slice", "policy"]),
    alwaysForbidden: Object.freeze(["role/company research unless needed for domain rejection"]),
  },
  "resume-advisor": {
    metadata: Object.freeze(["workflow summaries", "validation summaries"]),
    reviewedSemantic: Object.freeze(["no additional raw access"]),
    alwaysForbidden: Object.freeze(["raw private source bodies"]),
  },
});
export const DISCLOSURE_MATRIX = DISCLOSURE_POLICIES;

function freezeState(state: RunPrivacyState): RunPrivacyState {
  if (state.authorization) Object.freeze(state.authorization);
  return Object.freeze(state);
}

function normalizeInputCategories(categories: readonly string[]): readonly string[] {
  if (!Array.isArray(categories) || categories.length === 0 || categories.length > 32) {
    throw new PrivacyAuthorizationError("invalid-categories", "At least one bounded disclosure category is required");
  }
  const result: string[] = [];
  for (const category of categories) {
    const value = normalizeMetadataString(category, "disclosure category");
    if (!/^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,127}$/.test(value)) {
      throw new PrivacyAuthorizationError("invalid-categories", "Disclosure categories must be identifiers");
    }
    if (result.includes(value)) {
      throw new PrivacyAuthorizationError("invalid-categories", "Disclosure categories must be exact and unique");
    }
    result.push(value);
  }
  return Object.freeze(result);
}

function normalizeMinimumSlices(
  slices: readonly (string | SourceSliceDescriptor)[],
): readonly SourceSliceDescriptor[] {
  if (!Array.isArray(slices) || slices.length === 0 || slices.length > 32) {
    throw new PrivacyAuthorizationError("invalid-slices", "At least one bounded minimum source slice is required");
  }
  const result = slices.map((slice) => normalizeSliceDescriptor(slice));
  const seen = new Set<string>();
  for (const slice of result) {
    const hasConsumer = slice.consumer !== undefined || (slice.consumers !== undefined && slice.consumers.length > 0);
    if (!hasConsumer || slice.purpose === undefined || slice.purpose.length === 0) {
      throw new PrivacyAuthorizationError("invalid-slices", "Every minimum slice requires allowed consumer(s) and purpose");
    }
    const key = JSON.stringify(slice);
    if (seen.has(key)) {
      throw new PrivacyAuthorizationError("invalid-slices", "Minimum slices must be exact and unique");
    }
    seen.add(key);
  }
  return Object.freeze(result);
}
function normalizeConsumerIdentities(
  input: ReviewedSemanticAuthorizationInput,
  slices: readonly SourceSliceDescriptor[],
): ConsumerIdentityMap {
  const source = input.consumerIdentities ?? input.consumer_identities;
  if (!source) {
    throw new PrivacyAuthorizationError("invalid-provider", "Per-consumer provider/model identities are required");
  }
  const result: Partial<Record<CanonicalDisclosureConsumer, ProviderIdentity>> = {};
  for (const [rawConsumer, identityInput] of Object.entries(source as ConsumerIdentityMapInput)) {
    let consumer: CanonicalDisclosureConsumer;
    try {
      consumer = canonicalConsumer(rawConsumer as DisclosureConsumer);
    } catch {
      throw new PrivacyAuthorizationError("invalid-provider", "Consumer identity map contains an unknown consumer");
    }
    if (!identityInput || typeof identityInput.provider !== "string" || typeof identityInput.model !== "string") {
      throw new PrivacyAuthorizationError("invalid-provider", `Identity for ${consumer} requires provider and model`);
    }
    const provider = normalizeMetadataString(identityInput.provider, `${consumer} provider`);
    const model = normalizeMetadataString(identityInput.model, `${consumer} model`);
    const locality =
      identityInput.locality ??
      identityInput.providerLocality ??
      identityInput.localVsRemote ??
      (identityInput.isLocal === undefined ? undefined : identityInput.isLocal ? "local" : "remote");
    if (locality !== "local" && locality !== "remote") {
      throw new PrivacyAuthorizationError("invalid-provider", `Identity for ${consumer} requires local/remote locality`);
    }
    result[consumer] = Object.freeze({
      provider,
      model,
      locality,
      providerLocality: locality,
      localVsRemote: locality,
      isLocal: locality === "local",
    });
  }
  const required = new Set<CanonicalDisclosureConsumer>();
  for (const slice of slices) {
    if (slice.consumer !== undefined) required.add(canonicalConsumer(slice.consumer));
    for (const consumer of slice.consumers ?? []) required.add(canonicalConsumer(consumer));
  }
  for (const consumer of required) {
    if (result[consumer] === undefined) {
      throw new PrivacyAuthorizationError("invalid-provider", `Identity for ${consumer} is required by a minimum slice`);
    }
  }
  return Object.freeze(result);
}

function resolveLocality(input: ReviewedSemanticAuthorizationInput): "local" | "remote" {
  const locality =
    input.locality ??
    input.providerLocality ??
    input.localVsRemote ??
    (input.isLocal === undefined ? undefined : input.isLocal ? "local" : "remote");
  if (locality !== "local" && locality !== "remote") {
    throw new PrivacyAuthorizationError("invalid-provider", "Provider locality must be local or remote");
  }
  return locality;
}

function resolveSessionInput(input: ReviewedSemanticAuthorizationInput): SessionJsonlObservationInput {
  const selected = input.observedSession ?? input.session ?? input.sessionJsonl;
  if (selected) return selected;
  if (input.sessionJsonlMode === undefined) {
    throw new PrivacyAuthorizationError("invalid-session", "Observed OMP session JSONL metadata is required");
  }
  return {
    ...(input.sessionJsonlPath === undefined ? {} : { path: input.sessionJsonlPath }),
    mode: input.sessionJsonlMode,
    ...(input.sessionJsonlOwnerUid === undefined ? {} : { ownerUid: input.sessionJsonlOwnerUid }),
    ...(input.sessionJsonlOwner === undefined ? {} : { owner: input.sessionJsonlOwner }),
    ...(input.sessionJsonlOwnerUid === undefined ? {} : { expectedOwnerUid: input.sessionJsonlOwnerUid }),
  };
}

function stateDefaultRunId(now: string): string {
  // This ID contains no source information.  The extension may supply a stable
  // run ID when it has one; otherwise timestamp + random UUID is sufficient.
  const maybeCrypto = globalThis as typeof globalThis & { crypto?: { randomUUID?: () => string } };
  const random = maybeCrypto.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
  return `resume-${now.replace(/[^0-9]/g, "").slice(0, 17)}-${random.slice(0, 12)}`;
}

export function createRunPrivacyState(input: CreateRunPrivacyStateInput = {}): RunPrivacyState {
  const startedAt = normalizeTimestamp(input.startedAt);
  const runId = safeRunId(input.runId, stateDefaultRunId(startedAt));
  const retention = input.retention === undefined ? DEFAULT_RETENTION : normalizeRetention(input.retention);
  return freezeState({ runId, mode: "metadata-only", startedAt, retention });
}

export function authorizeReviewedSemantic(
  state: RunPrivacyState,
  input: ReviewedSemanticAuthorizationInput,
): RunPrivacyState {
  if (state.mode !== "metadata-only" || state.authorization) {
    throw new PrivacyAuthorizationError("mode-already-authorized", "Reviewed-semantic authorization is already present");
  }
  if (input.explicitAuthorization === false || input.userAuthorized === false) {
    throw new PrivacyAuthorizationError("unsafe-authorization", "Reviewed-semantic mode requires explicit user authorization");
  }
  if (
    input.authorizationId !== undefined &&
    input.authorization_id !== undefined &&
    input.authorizationId !== input.authorization_id
  ) {
    throw new PrivacyAuthorizationError("unsafe-authorization", "Authorization ID aliases disagree");
  }
  assertSafeMetadata(input, "authorization");
  assertSafeMetadata(
    {
      provider: input.provider,
      model: input.model,
      locality: input.locality,
      providerLocality: input.providerLocality,
      localVsRemote: input.localVsRemote,
      isLocal: input.isLocal,
      categories: input.categories ?? input.requestedCategories,
      minimumSlices: input.minimumSlices ?? input.minimumRequestedSlices,
      sessionJsonlPath: input.sessionJsonlPath,
      sessionJsonlMode: input.sessionJsonlMode,
      sessionJsonlOwnerUid: input.sessionJsonlOwnerUid,
      sessionJsonlOwner: input.sessionJsonlOwner,
      sessionPermissionsPrivate: input.sessionPermissionsPrivate,
      sessionOwnerMatches: input.sessionOwnerMatches,
      observedSession: input.observedSession,
      sessionDirectory: input.sessionDirectory,
      observedSessionDirectory: input.observedSessionDirectory,
      retention: input.retention ?? input.retentionPolicy,
      authorizedAt: input.authorizedAt ?? input.authorizationTimestamp,
      authorizationId: input.authorizationId ?? input.authorization_id,
      explicitAuthorization: input.explicitAuthorization,
      userAuthorized: input.userAuthorized,
      runId: input.runId,
    },
    "authorization",
  );
  const provider = normalizeMetadataString(input.provider, "provider");
  const model = normalizeMetadataString(input.model, "model");
  if (
    !/^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,127}$/.test(provider) ||
    !/^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,191}$/.test(model)
  ) {
    throw new PrivacyAuthorizationError("invalid-provider", "Provider and model must be bounded identifiers");
  }
  const locality = resolveLocality(input);
  const categoryInput = input.categories ?? input.requestedCategories;
  const sliceInput = input.minimumSlices ?? input.minimumRequestedSlices;
  if (!categoryInput) {
    throw new PrivacyAuthorizationError("invalid-categories", "Disclosure categories are required");
  }
  if (!sliceInput) {
    throw new PrivacyAuthorizationError("invalid-slices", "Minimum source slices are required");
  }
  const categories = normalizeInputCategories(categoryInput);
  const minimumSlices = normalizeMinimumSlices(sliceInput);
  const consumerIdentities = normalizeConsumerIdentities(input, minimumSlices);
  const observation = normalizeSessionObservation(resolveSessionInput(input), input.sessionJsonlPath);
  if (!observation.isRegularFile) {
    throw new PrivacyAuthorizationError("invalid-session", "OMP session JSONL path must be a regular file");
  }
  if (!observation.privatePermissions || !observation.ownerMatches) {
    throw new PrivacyAuthorizationError("invalid-session", "OMP session JSONL must be private and owned by the current user");
  }
  const directoryInput = input.observedSessionDirectory ?? input.sessionDirectory;
  if (!directoryInput) {
    throw new PrivacyAuthorizationError("invalid-session", "Observed OMP session directory metadata is required");
  }
  const directoryObservation = normalizeSessionDirectoryObservation(
    directoryInput,
    dirname(observation.path),
  );
  if (
    !directoryObservation.isDirectory ||
    !directoryObservation.privatePermissions ||
    !directoryObservation.ownerMatches
  ) {
    throw new PrivacyAuthorizationError("invalid-session", "OMP session directory must be 0700-equivalent and owned by the current user");
  }
  const retention = normalizeRetention(input.retention ?? input.retentionPolicy);
  const authorizedAt = normalizeTimestamp(input.authorizedAt ?? input.authorizationTimestamp);
  const runId = input.runId ?? state.runId;
  if (runId !== state.runId) {
    throw new PrivacyAuthorizationError("run-mismatch", "Authorization run ID does not match local run state");
  }
  const maybeCrypto = globalThis as typeof globalThis & { crypto?: { randomUUID?: () => string } };
  const fallbackAuthorizationId = `auth-${state.runId}-${authorizedAt.replace(/[^0-9]/g, "").slice(0, 17)}-${(maybeCrypto.crypto?.randomUUID?.() ?? Math.random().toString(36)).slice(0, 12)}`;
  const authorizationId = safeAuthorizationId(
    input.authorizationId ?? input.authorization_id,
    fallbackAuthorizationId,
  );
  const authorization: ReviewedSemanticAuthorization = Object.freeze({
    authorizationId,
    authorization_id: authorizationId,
    provider,
    model,
    locality,
    providerLocality: locality,
    localVsRemote: locality,
    isLocal: locality === "local",
    consumerIdentities,
    categories,
    requestedCategories: categories,
    minimumSlices,
    minimumRequestedSlices: minimumSlices,
    sessionJsonlPath: observation.path,
    sessionObservation: observation,
    sessionDirectoryPath: directoryObservation.path,
    sessionDirectoryObservation: directoryObservation,
    sessionJsonlMode: observation.mode,
    ...(observation.ownerUid === undefined ? {} : { sessionJsonlOwnerUid: observation.ownerUid }),
    sessionJsonlOwnerMatches: observation.ownerMatches,
    sessionJsonlPermissionsPrivate: observation.privatePermissions,
    sessionDirectoryMode: directoryObservation.mode,
    ...(directoryObservation.ownerUid === undefined ? {} : { sessionDirectoryOwnerUid: directoryObservation.ownerUid }),
    sessionDirectoryOwnerMatches: directoryObservation.ownerMatches,
    sessionDirectoryPermissionsPrivate: directoryObservation.privatePermissions,
    sessionPath: observation.path,
    retention,
    retentionPolicy: retention,
    authorizedAt,
    authorizationTimestamp: authorizedAt,
    runId: state.runId,
  });
  return freezeState({
    runId: state.runId,
    mode: "reviewed-semantic",
    startedAt: state.startedAt,
    authorizationId,
    retention,
    authorization,
  });
}

export function disclosureFor(state: RunPrivacyState, consumer: DisclosureConsumer): DisclosurePolicy {
  const canonical = canonicalConsumer(consumer);
  const definition = DISCLOSURE_POLICIES[canonical];
  return Object.freeze({
    consumer: canonical,
    mode: state.mode,
    metadata: definition.metadata,
    reviewedSemantic: definition.reviewedSemantic,
    alwaysForbidden: definition.alwaysForbidden,
    rawSourceAllowed:
      state.mode === "reviewed-semantic" &&
      state.authorization !== undefined &&
      canonical !== "resume-advisor",
  });
}

export function summarizePrivacyState(state: RunPrivacyState): PrivacyStatusSummary {
  const auth = state.authorization;
  return Object.freeze({
    runId: state.runId,
    mode: state.mode,
    rawSourceAllowed: state.mode === "reviewed-semantic" && state.authorization !== undefined,
    ...(state.authorizationId === undefined ? {} : { authorizationId: state.authorizationId }),
    authorization: Object.freeze({
      present: auth !== undefined,
      ...(auth
        ? {
            authorizationId: auth.authorizationId,
            authorization_id: auth.authorization_id,
            provider: auth.provider,
            model: auth.model,
            locality: auth.locality,
            providerLocality: auth.providerLocality,
            localVsRemote: auth.localVsRemote,
            isLocal: auth.isLocal,
            consumerIdentities: auth.consumerIdentities,
            categories: auth.categories,
            requestedCategories: auth.requestedCategories,
            minimumSlices: auth.minimumSlices,
            minimumRequestedSlices: auth.minimumRequestedSlices,
            categoryCount: auth.categories.length,
            minimumSliceCount: auth.minimumSlices.length,
            sessionJsonlPath: auth.sessionJsonlPath,
            sessionObservation: auth.sessionObservation,
            sessionDirectoryPath: auth.sessionDirectoryPath,
            sessionDirectoryObservation: auth.sessionDirectoryObservation,
            sessionJsonlMode: auth.sessionJsonlMode,
            sessionJsonlPermissionsPrivate: auth.sessionJsonlPermissionsPrivate,
            sessionJsonlOwnerMatches: auth.sessionJsonlOwnerMatches,
            sessionDirectoryMode: auth.sessionDirectoryMode,
            sessionDirectoryPermissionsPrivate: auth.sessionDirectoryPermissionsPrivate,
            sessionDirectoryOwnerMatches: auth.sessionDirectoryOwnerMatches,
            authorizedAt: auth.authorizedAt,
            authorizationTimestamp: auth.authorizationTimestamp,
          }
        : {
            categories: Object.freeze([] as string[]),
            requestedCategories: Object.freeze([] as string[]),
            minimumSlices: Object.freeze([] as SourceSliceDescriptor[]),
            minimumRequestedSlices: Object.freeze([] as SourceSliceDescriptor[]),
            categoryCount: 0,
            minimumSliceCount: 0,
          }),
    }),
    retention: Object.freeze({
      strategy: state.retention.strategy,
      cleanupSupported: state.retention.cleanupSupported,
      ...(state.retention.maxAgeSeconds === undefined ? {} : { maxAgeSeconds: state.retention.maxAgeSeconds }),
      cleanupLimits: state.retention.cleanupLimits,
      deletionGuarantee: state.retention.deletionGuarantee,
    }),
  });
}

export const getPrivacyStatus = summarizePrivacyState;
export const getDisclosurePolicy = disclosureFor;
export const defaultPrivacyMode: PrivacyMode = "metadata-only";

export function isMetadataOnly(state: RunPrivacyState): boolean {
  return state.mode === "metadata-only";
}

export function isReviewedSemantic(state: RunPrivacyState): boolean {
  return state.mode === "reviewed-semantic" && state.authorization !== undefined;
}

export function sessionObservationPrivate(state: RunPrivacyState): boolean {
  return state.authorization ? hasPrivatePermissions(state.authorization.sessionObservation.mode) : false;
}
export const createPrivacyState = createRunPrivacyState;
export const grantReviewedSemantic = authorizeReviewedSemantic;
