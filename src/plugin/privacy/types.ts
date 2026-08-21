/** Minimal filesystem stat shape needed by the privacy boundary. */

/** The only two source-disclosure modes supported by a run. */
export type PrivacyMode = "metadata-only" | "reviewed-semantic";

export type ProviderLocality = "local" | "remote";

export type DisclosureConsumer =
  | "main"
  | "main-model"
  | "source-mapper"
  | "role-analyst"
  | "requirement-reviewer"
  | "evidence-reviewer"
  | "contribution-reviewer"
  | "privacy-reviewer"
  | "resume-advisor"
  | "advisor";

export type CanonicalDisclosureConsumer =
  | "main"
  | "source-mapper"
  | "role-analyst"
  | "requirement-reviewer"
  | "evidence-reviewer"
  | "contribution-reviewer"
  | "privacy-reviewer"
  | "resume-advisor";

export interface ProviderIdentityInput {
  readonly provider: string;
  readonly model: string;
  readonly locality?: ProviderLocality;
  readonly providerLocality?: ProviderLocality;
  readonly localVsRemote?: ProviderLocality;
  readonly isLocal?: boolean;
}

export interface ProviderIdentity {
  readonly provider: string;
  readonly model: string;
  readonly locality: ProviderLocality;
  readonly providerLocality: ProviderLocality;
  readonly localVsRemote: ProviderLocality;
  readonly isLocal: boolean;
}

export type ConsumerIdentityMapInput = Partial<Record<CanonicalDisclosureConsumer, ProviderIdentityInput>>;
export type ConsumerIdentityMap = Readonly<Partial<Record<CanonicalDisclosureConsumer, ProviderIdentity>>>;
export type RetentionStrategy =
  | "not-applicable"
  | "cleanup-on-stop"
  | "retain-until-expiry"
  | "retain";

export type DeletionGuarantee = "verified" | "not-guaranteed";

/**
 * A path/range descriptor, never source text.  Paths are deliberately kept
 * separate from source contents so an authorization record cannot become a
 * source cache.
 */
export interface SourceSliceDescriptor {
  readonly path: string;
  readonly startLine?: number;
  readonly endLine?: number;
  readonly lineStart?: number;
  readonly lineEnd?: number;
  readonly category?: string;
  readonly sourceId?: string;
  readonly sliceId?: string;
  readonly consumer?: DisclosureConsumer;
  readonly consumers?: readonly DisclosureConsumer[];
  readonly purpose?: string;
}

export type MinimumSliceInput = string | SourceSliceDescriptor;

export interface RetentionPolicyInput {
  readonly strategy?: RetentionStrategy;
  readonly maxAgeSeconds?: number;
  readonly cleanupSupported?: boolean;
  readonly cleanupLimit?: string;
  readonly cleanupLimits?: readonly string[];
  readonly deletionGuaranteed?: boolean;
}

export interface RetentionPolicy {
  readonly strategy: RetentionStrategy;
  readonly maxAgeSeconds?: number;
  readonly cleanupSupported: boolean;
  readonly cleanupLimits: readonly string[];
  /** False/unknown cleanup support is never represented as a deletion claim. */
  readonly deletionGuarantee: DeletionGuarantee;
}

export interface SessionJsonlObservationInput {
  readonly path?: string;
  readonly mode?: number | string;
  readonly observedMode?: number | string;
  readonly ownerUid?: number;
  readonly observedOwnerUid?: number;
  readonly owner?: string;
  readonly observedOwner?: string;
  readonly expectedOwnerUid?: number;
  readonly expectedOwner?: string;
  readonly isRegularFile?: boolean;
  readonly regularFile?: boolean;
  readonly permissionsPrivate?: boolean;
  readonly ownerMatches?: boolean;
}

export interface SessionJsonlObservation {
  readonly path: string;
  readonly mode: number;
  readonly ownerUid?: number;
  readonly owner?: string;
  readonly expectedOwnerUid?: number;
  readonly expectedOwner?: string;
  readonly isRegularFile: boolean;
  readonly privatePermissions: boolean;
  readonly ownerMatches: boolean;
}
export interface SessionDirectoryObservationInput {
  readonly path?: string;
  readonly mode?: number | string;
  readonly observedMode?: number | string;
  readonly ownerUid?: number;
  readonly observedOwnerUid?: number;
  readonly owner?: string;
  readonly observedOwner?: string;
  readonly expectedOwnerUid?: number;
  readonly expectedOwner?: string;
  readonly isDirectory?: boolean;
  readonly directory?: boolean;
  readonly permissionsPrivate?: boolean;
  readonly ownerMatches?: boolean;
}

export interface SessionDirectoryObservation {
  readonly path: string;
  readonly mode: number;
  readonly ownerUid?: number;
  readonly owner?: string;
  readonly expectedOwnerUid?: number;
  readonly expectedOwner?: string;
  readonly isDirectory: boolean;
  readonly privatePermissions: boolean;
  readonly ownerMatches: boolean;
}

export interface ReviewedSemanticAuthorizationInput {
  readonly provider: string;
  readonly model: string;
  readonly locality?: ProviderLocality;
  readonly providerLocality?: ProviderLocality;
  readonly localVsRemote?: ProviderLocality;
  readonly isLocal?: boolean;
  readonly consumerIdentities?: ConsumerIdentityMapInput;
  readonly consumer_identities?: ConsumerIdentityMapInput;
  readonly categories?: readonly string[];
  readonly requestedCategories?: readonly string[];
  readonly minimumSlices?: readonly MinimumSliceInput[];
  readonly minimumRequestedSlices?: readonly MinimumSliceInput[];
  readonly sessionJsonlPath?: string;
  readonly sessionJsonlMode?: number | string;
  readonly sessionJsonlOwnerUid?: number;
  readonly sessionJsonlOwner?: string;
  readonly sessionPermissionsPrivate?: boolean;
  readonly sessionOwnerMatches?: boolean;
  readonly session?: SessionJsonlObservationInput;
  readonly sessionJsonl?: SessionJsonlObservationInput;
  readonly observedSession?: SessionJsonlObservationInput;
  readonly sessionDirectory?: SessionDirectoryObservationInput;
  readonly observedSessionDirectory?: SessionDirectoryObservationInput;
  readonly retention?: RetentionPolicyInput;
  readonly retentionPolicy?: RetentionPolicyInput;
  readonly authorizedAt?: string | number | Date;
  readonly authorizationTimestamp?: string | number | Date;
  readonly authorizationId?: string;
  readonly authorization_id?: string;
  readonly explicitAuthorization?: boolean;
  readonly userAuthorized?: boolean;
  readonly runId?: string;
}
export interface ReviewedSemanticAuthorization {
  readonly authorizationId: string;
  readonly authorization_id: string;
  readonly provider: string;
  readonly model: string;
  readonly locality: ProviderLocality;
  readonly providerLocality: ProviderLocality;
  readonly localVsRemote: ProviderLocality;
  readonly isLocal: boolean;
  readonly consumerIdentities: ConsumerIdentityMap;
  readonly categories: readonly string[];
  readonly requestedCategories: readonly string[];
  readonly minimumSlices: readonly SourceSliceDescriptor[];
  readonly minimumRequestedSlices: readonly SourceSliceDescriptor[];
  readonly sessionJsonlPath: string;
  readonly sessionObservation: SessionJsonlObservation;
  readonly sessionDirectoryPath: string;
  readonly sessionDirectoryObservation: SessionDirectoryObservation;
  readonly sessionJsonlMode: number;
  readonly sessionJsonlOwnerUid?: number;
  readonly sessionJsonlOwnerMatches: boolean;
  readonly sessionJsonlPermissionsPrivate: boolean;
  readonly sessionDirectoryMode: number;
  readonly sessionDirectoryOwnerUid?: number;
  readonly sessionDirectoryOwnerMatches: boolean;
  readonly sessionDirectoryPermissionsPrivate: boolean;
  readonly sessionPath: string;
  readonly retention: RetentionPolicy;
  readonly retentionPolicy: RetentionPolicy;
  readonly authorizedAt: string;
  readonly authorizationTimestamp: string;
  readonly runId: string;
}

export interface RunPrivacyState {
  readonly runId: string;
  readonly mode: PrivacyMode;
  readonly startedAt: string;
  readonly authorizationId?: string;
  readonly retention: RetentionPolicy;
  readonly authorization?: ReviewedSemanticAuthorization;
}
/** Backwards-compatible descriptive alias for Extension consumers. */
export type PrivacyState = RunPrivacyState;
export type ReviewedSemanticGrant = ReviewedSemanticAuthorization;

export interface CreateRunPrivacyStateInput {
  readonly runId?: string;
  readonly startedAt?: string | number | Date;
  readonly retention?: RetentionPolicyInput;
}

export interface DisclosurePolicy {
  readonly consumer: CanonicalDisclosureConsumer;
  readonly mode: PrivacyMode;
  readonly metadata: readonly string[];
  readonly reviewedSemantic: readonly string[];
  readonly alwaysForbidden: readonly string[];
  readonly rawSourceAllowed: boolean;
}

export type SourceSliceRejectionCode =
  | "metadata-only"
  | "invalid-path"
  | "secret-looking-path"
  | "contact-path"
  | "forbidden-policy"
  | "whole-repository"
  | "unrelated-slice"
  | "oversize"
  | "invalid-range"
  | "forbidden-content"
  | "contact-content"
  | "credential-content"
  | "missing-authorization"
  | "consumer-forbidden";

export interface SourceSliceRequest extends SourceSliceDescriptor {
  readonly consumer: DisclosureConsumer;
  readonly content?: string | Uint8Array;
  readonly bytes?: number;
  readonly maxBytes?: number;
  readonly wholeRepository?: boolean;
  readonly repositoryRoot?: string;
  readonly authorizationId?: string;
  readonly authorization_id?: string;
  readonly provider?: string;
  readonly model?: string;
  readonly locality?: ProviderLocality;
  /** Parser-derived policy metadata; no source body is permitted here. */
  readonly effectivePolicy?: string;
  readonly privacyLevel?: string;
  readonly policy?: string;
  readonly ancestorPolicies?: readonly string[];
  readonly blockedByPolicy?: boolean;
  readonly requestId?: string;
}

export interface SourceSliceAllowed {
  readonly ok: true;
  readonly authorizationId: string;
  readonly provider: string;
  readonly model: string;
  readonly locality: ProviderLocality;
  readonly requestId?: string;
  readonly mode: "reviewed-semantic";
  readonly consumer: CanonicalDisclosureConsumer;
  readonly purpose: string;
  readonly path: string;
  readonly startLine?: number;
  readonly endLine?: number;
  readonly category?: string;
  readonly bytes: number;
  readonly content?: string;
}

export interface SourceSliceDenied {
  readonly ok: false;
  readonly requestId?: string;
  readonly code: SourceSliceRejectionCode;
  readonly reason: string;
}

export type SourceSlicePrefilterResult = SourceSliceAllowed | SourceSliceDenied;

export interface SessionCleanupResult {
  readonly supported: boolean;
  readonly attempted: boolean;
  readonly deleted: boolean;
  readonly verified: boolean;
  readonly limit?: string;
  readonly note?: string;
}
export interface SessionCleanupOptions {
  readonly remove?: (path: string) => void;
}

export interface SessionAuditOptions {
  readonly path?: string;
  readonly repositoryRoot?: string;
  readonly observation?: SessionJsonlObservationInput;
  readonly directoryObservation?: SessionDirectoryObservationInput;
  readonly cleanup?: SessionCleanupResult;
  readonly maxLines?: number;
  readonly maxTreeEntries?: number;
}
export interface SessionDirectoryAuditSummary {
  readonly path: string;
  readonly exists: boolean;
  readonly isDirectory: boolean;
  readonly privatePermissions: boolean;
  readonly observedMode?: number;
  readonly ownerMatches: boolean;
}

export interface SessionArtifactFileAuditSummary {
  readonly path: string;
  readonly kind: "jsonl" | "markdown" | "other";
  readonly mode?: number;
  readonly privatePermissions: boolean;
  readonly ownerMatches: boolean;
  readonly containsAuthorizedReceipt: boolean;
}

export interface SessionArtifactTreeAuditSummary {
  readonly directoryCount: number;
  readonly fileCount: number;
  readonly jsonlCount: number;
  readonly markdownCount: number;
  readonly weakDirectoryCount: number;
  readonly weakFileCount: number;
  readonly receiptUnprovenFileCount: number;
  readonly disclosedSliceCount: number;
  readonly outOfScopeSliceCount: number;
  readonly forbiddenSentinelCount: number;
  readonly malformedLineCount: number;
  readonly files: readonly SessionArtifactFileAuditSummary[];
  readonly scopeProof: "receipts-verified" | "receipts-incomplete" | "not-applicable";
}

export interface SessionAuditReport {
  readonly ok: boolean;
  readonly path: string;
  readonly exists: boolean;
  readonly regularFile: boolean;
  readonly privatePermissions: boolean;
  readonly observedMode?: number;
  readonly ownerMatches: boolean;
  readonly parentDirectory: SessionDirectoryAuditSummary;
  readonly tree: SessionArtifactTreeAuditSummary;
  readonly effectivePrivacy: "private" | "weak-directory" | "weak-file" | "unavailable";
  readonly disclosedSliceCount: number;
  readonly outOfScopeSliceCount: number;
  readonly forbiddenSentinelCount: number;
  readonly malformedLineCount: number;
  readonly lineLimitExceeded: boolean;
  readonly retainedArtifact: boolean;
  readonly cleanup: SessionCleanupResult;
  readonly deletionClaimed: boolean;
  readonly errors: readonly string[];
}

/** Narrow stat shape used by tests and by the OMP session audit. */
export type SessionStatLike = {
  readonly mode: number;
  readonly uid?: number;
  readonly isFile: () => boolean;
};

export interface PrivacyStatusSummary {
  readonly runId: string;
  readonly mode: PrivacyMode;
  readonly rawSourceAllowed: boolean;
  readonly authorizationId?: string;
  readonly authorization: {
    readonly present: boolean;
    readonly authorizationId?: string;
    readonly authorization_id?: string;
    readonly provider?: string;
    readonly model?: string;
    readonly locality?: ProviderLocality;
    readonly providerLocality?: ProviderLocality;
    readonly localVsRemote?: ProviderLocality;
    readonly isLocal?: boolean;
    readonly consumerIdentities?: ConsumerIdentityMap;
    readonly categories: readonly string[];
    readonly requestedCategories: readonly string[];
    readonly minimumSlices: readonly SourceSliceDescriptor[];
    readonly minimumRequestedSlices: readonly SourceSliceDescriptor[];
    readonly categoryCount: number;
    readonly minimumSliceCount: number;
    readonly sessionJsonlPath?: string;
    readonly sessionObservation?: SessionJsonlObservation;
    readonly sessionDirectoryPath?: string;
    readonly sessionDirectoryObservation?: SessionDirectoryObservation;
    readonly sessionJsonlMode?: number;
    readonly sessionJsonlPermissionsPrivate?: boolean;
    readonly sessionJsonlOwnerMatches?: boolean;
    readonly sessionDirectoryMode?: number;
    readonly sessionDirectoryPermissionsPrivate?: boolean;
    readonly sessionDirectoryOwnerMatches?: boolean;
    readonly authorizedAt?: string;
    readonly authorizationTimestamp?: string;
  };
  readonly retention: {
    readonly strategy: RetentionStrategy;
    readonly cleanupSupported: boolean;
    readonly maxAgeSeconds?: number;
    readonly cleanupLimits: readonly string[];
    readonly deletionGuarantee: DeletionGuarantee;
  };
}

export interface SourceSliceReader {
  (request: Readonly<SourceSliceRequest>): string | Uint8Array | Promise<string | Uint8Array>;
}

