/**
 * Canonical checks that standard Draft 2020-12 cannot express: numeric
 * cross-field ordering, uniqueness by one object key, and cross-array
 * identity/reference closure. Shape, paths, enums, and every conditional
 * contract remain in the authoritative JSON schemas and are enforced by Ajv.
 */

import type {
  JsonArray,
  JsonObject,
  JsonValue,
  SchemaName,
  SchemaValidationIssue,
} from "./schema.ts";

function pointerToken(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function issue(
  instancePath: string,
  contract: string,
  message: string,
  parameters: Readonly<Record<string, unknown>> = {},
): SchemaValidationIssue {
  return Object.freeze({
    instancePath,
    schemaPath: `#/x-canonical-contract/${contract}`,
    keyword: contract,
    message,
    parameters: Object.freeze({ ...parameters }),
  });
}

function isJsonObject(value: JsonValue | undefined): value is JsonObject {
  return value !== undefined && value !== null && typeof value === "object" && !Array.isArray(value);
}

function isJsonArray(value: JsonValue | undefined): value is JsonArray {
  return Array.isArray(value);
}

function objectArray(value: JsonObject, key: string): readonly JsonObject[] {
  const nested = value[key];
  if (!isJsonArray(nested)) return [];
  return nested.filter(isJsonObject);
}

function stringField(value: JsonObject, key: string): string | undefined {
  const nested = value[key];
  return typeof nested === "string" ? nested : undefined;
}


function collectSpanOrderingIssues(
  value: JsonValue,
  instancePath: string,
  issues: SchemaValidationIssue[],
): void {
  if (value === null || typeof value !== "object") return;
  if (isJsonArray(value)) {
    for (const [index, nested] of value.entries()) {
      collectSpanOrderingIssues(nested, `${instancePath}/${index}`, issues);
    }
    return;
  }

  const startLine = value.start_line;
  const endLine = value.end_line;
  const startByte = value.start_byte;
  const endByte = value.end_byte;
  if (
    typeof startLine === "number"
    && typeof endLine === "number"
    && typeof startByte === "number"
    && typeof endByte === "number"
  ) {
    if (endLine < startLine) {
      issues.push(issue(
        instancePath,
        "span-order",
        "source span end_line must be greater than or equal to start_line",
        { startLine, endLine },
      ));
    }
    if (endByte <= startByte) {
      issues.push(issue(
        instancePath,
        "span-order",
        "source span end_byte must be greater than start_byte",
        { startByte, endByte },
      ));
    }
  }


  for (const [key, nested] of Object.entries(value)) {
    collectSpanOrderingIssues(nested, `${instancePath}/${pointerToken(key)}`, issues);
  }
}

function collectDuplicateFieldIssues(
  items: readonly JsonObject[],
  field: string,
  instancePath: string,
  contract: string,
  message: string,
  issues: SchemaValidationIssue[],
): void {
  const seen = new Set<string>();
  for (const [index, item] of items.entries()) {
    const identifier = stringField(item, field);
    if (identifier === undefined) continue;
    if (seen.has(identifier)) {
      issues.push(issue(`${instancePath}/${index}/${pointerToken(field)}`, contract, message, {
        field,
        identifier,
      }));
    } else {
      seen.add(identifier);
    }
  }
}

function collectSourceMapIssues(value: JsonObject, issues: SchemaValidationIssue[]): void {
  const documents = objectArray(value, "documents");
  const sections = objectArray(value, "sections");
  const blocks = objectArray(value, "blocks");
  const proposals = objectArray(value, "proposals");
  collectDuplicateFieldIssues(
    documents,
    "document_id",
    "/documents",
    "duplicate-document-id",
    "source map contains duplicate document IDs",
    issues,
  );
  collectDuplicateFieldIssues(
    documents,
    "path",
    "/documents",
    "duplicate-document-path",
    "source map contains duplicate document paths",
    issues,
  );
  collectDuplicateFieldIssues(
    sections,
    "section_id",
    "/sections",
    "duplicate-section-id",
    "source map contains duplicate section IDs",
    issues,
  );
  collectDuplicateFieldIssues(
    blocks,
    "block_id",
    "/blocks",
    "duplicate-block-id",
    "source map contains duplicate block IDs",
    issues,
  );
  collectDuplicateFieldIssues(
    proposals,
    "proposal_id",
    "/proposals",
    "duplicate-proposal-id",
    "source map contains duplicate proposal IDs",
    issues,
  );

  const documentIds = new Set(documents.map((document) => stringField(document, "document_id")).filter((id) => id !== undefined));
  const documentByPath = new Map<string, JsonObject>();
  for (const document of documents) {
    const path = stringField(document, "path");
    if (path !== undefined && !documentByPath.has(path)) documentByPath.set(path, document);
  }
  const sectionById = new Map<string, JsonObject>();
  for (const section of sections) {
    const sectionId = stringField(section, "section_id");
    if (sectionId !== undefined && !sectionById.has(sectionId)) sectionById.set(sectionId, section);
  }
  const blockById = new Map<string, JsonObject>();
  for (const block of blocks) {
    const blockId = stringField(block, "block_id");
    if (blockId !== undefined && !blockById.has(blockId)) blockById.set(blockId, block);
  }

  for (const [index, section] of sections.entries()) {
    const sectionId = stringField(section, "section_id") ?? "<unknown>";
    const documentId = stringField(section, "document_id");
    if (documentId !== undefined && !documentIds.has(documentId)) {
      issues.push(issue(
        `/sections/${index}/document_id`,
        "unknown-document-reference",
        `section ${JSON.stringify(sectionId)} references an unknown document`,
        { documentId },
      ));
    }
    const blockIds = section.block_ids;
    if (!Array.isArray(blockIds)) continue;
    for (const [blockIndex, blockId] of blockIds.entries()) {
      if (typeof blockId !== "string") continue;
      const block = blockById.get(blockId);
      if (block === undefined || stringField(block, "section_id") !== sectionId) {
        issues.push(issue(
          `/sections/${index}/block_ids/${blockIndex}`,
          "inconsistent-block-reference",
          `section ${JSON.stringify(sectionId)} references an inconsistent block`,
          { blockId },
        ));
      }
    }
  }

  for (const [index, block] of blocks.entries()) {
    const blockId = stringField(block, "block_id") ?? "<unknown>";
    const documentId = stringField(block, "document_id");
    if (documentId !== undefined && !documentIds.has(documentId)) {
      issues.push(issue(
        `/blocks/${index}/document_id`,
        "unknown-document-reference",
        `block ${JSON.stringify(blockId)} references an unknown document`,
        { documentId },
      ));
    }
    const sectionId = block.section_id;
    if (typeof sectionId === "string" && !sectionById.has(sectionId)) {
      issues.push(issue(
        `/blocks/${index}/section_id`,
        "unknown-section-reference",
        `block ${JSON.stringify(blockId)} references an unknown section`,
        { sectionId },
      ));
    }
  }

  for (const [index, proposal] of proposals.entries()) {
    const proposalId = stringField(proposal, "proposal_id") ?? "<unknown>";
    const source = proposal.source;
    if (!isJsonObject(source)) continue;
    const sourcePath = stringField(source, "path");
    const document = sourcePath === undefined ? undefined : documentByPath.get(sourcePath);
    if (document === undefined) {
      issues.push(issue(
        `/proposals/${index}/source/path`,
        "unknown-source-path",
        `proposal ${JSON.stringify(proposalId)} references an unknown source path`,
        sourcePath === undefined ? {} : { sourcePath },
      ));
    } else if (stringField(document, "source_hash") !== stringField(source, "source_hash")) {
      issues.push(issue(
        `/proposals/${index}/source/source_hash`,
        "source-hash-mismatch",
        `proposal ${JSON.stringify(proposalId)} source hash does not match its document`,
        sourcePath === undefined ? {} : { sourcePath },
      ));
    }
    const sectionId = source.section_id;
    if (typeof sectionId === "string" && !sectionById.has(sectionId)) {
      issues.push(issue(
        `/proposals/${index}/source/section_id`,
        "unknown-section-reference",
        `proposal ${JSON.stringify(proposalId)} references an unknown section`,
        { sectionId },
      ));
    }
    const blockId = source.block_id;
    if (typeof blockId === "string" && !blockById.has(blockId)) {
      issues.push(issue(
        `/proposals/${index}/source/block_id`,
        "unknown-block-reference",
        `proposal ${JSON.stringify(proposalId)} references an unknown block`,
        { blockId },
      ));
    }
  }
}


function collectEvidenceInputIssues(value: JsonObject, issues: SchemaValidationIssue[]): void {
  collectDuplicateFieldIssues(
    objectArray(value, "candidates"),
    "evidence_id",
    "/candidates",
    "duplicate-evidence-id",
    "normalized evidence input contains duplicate evidence IDs",
    issues,
  );
}

function collectReviewDecisionIssues(value: JsonObject, issues: SchemaValidationIssue[]): void {
  collectDuplicateFieldIssues(
    objectArray(value, "decisions"),
    "review_id",
    "/decisions",
    "duplicate-review-id",
    "review decisions contain duplicate review IDs",
    issues,
  );
}

function collectApprovedClaimIssues(value: JsonObject, issues: SchemaValidationIssue[]): void {
  collectDuplicateFieldIssues(
    objectArray(value, "claims"),
    "claim_id",
    "/claims",
    "duplicate-claim-id",
    "approved claims contain duplicate immutable claim IDs",
    issues,
  );
}

export function canonicalContractIssues(name: SchemaName, value: JsonObject): readonly SchemaValidationIssue[] {
  const issues: SchemaValidationIssue[] = [];
  collectSpanOrderingIssues(value, "", issues);
  switch (name) {
    case "source-map":
      collectSourceMapIssues(value, issues);
      break;
    case "normalized-role-input":
      break;
    case "normalized-evidence-input":
      collectEvidenceInputIssues(value, issues);
      break;
    case "review-decision":
      collectReviewDecisionIssues(value, issues);
      break;
    case "approved-claims":
      collectApprovedClaimIssues(value, issues);
      break;
  }
  return issues;
}
