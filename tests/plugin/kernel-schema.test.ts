import { describe, expect, test } from "bun:test";
import {
  AUTHORITATIVE_SCHEMAS,
  SCHEMA_NAMES,
  SUPPLEMENTAL_SCHEMA_NAMES,
  SchemaConfigurationError,
  SchemaValidationError,
  loadSchema,
  schemaName,
  validateSchemaDocument,
  type JsonObject,
  type SchemaName,
} from "../../src/kernel/schema.ts";

const ACCEPTED_DOCUMENTS: Readonly<Record<SchemaName, JsonObject>> = Object.freeze({
  "source-map": Object.freeze({
    schema_version: 1,
    documents: Object.freeze([]),
    sections: Object.freeze([]),
    blocks: Object.freeze([]),
    proposals: Object.freeze([]),
  }),
  "normalized-role-input": Object.freeze({
    schema_version: 1,
    input_id: "role-input.synthetic",
    domain: "role",
    proposals: Object.freeze([]),
    requirements: Object.freeze([]),
    unresolved_questions: Object.freeze([]),
  }),
  "normalized-evidence-input": Object.freeze({
    schema_version: 1,
    input_id: "evidence-input.synthetic",
    domain: "evidence",
    candidates: Object.freeze([]),
    unresolved_questions: Object.freeze([]),
  }),
  "review-decision": Object.freeze({
    schema_version: 1,
    decisions: Object.freeze([]),
  }),
  "approved-claims": Object.freeze({
    schema_version: 1,
    claims: Object.freeze([]),
  }),
});

describe("authoritative Draft 2020-12 IR schemas", () => {
  test("loads exactly the five immutable schema authorities", () => {
    expect(SCHEMA_NAMES).toEqual([
      "source-map",
      "normalized-role-input",
      "normalized-evidence-input",
      "review-decision",
      "approved-claims",
    ]);
    for (const name of SCHEMA_NAMES) {
      const schema = loadSchema(`${name}.schema.json`);
      expect(schema).toBe(AUTHORITATIVE_SCHEMAS[name]);
      expect(schema.$schema).toBe("https://json-schema.org/draft/2020-12/schema");
      expect(Object.isFrozen(schema)).toBe(true);
    }
  });

  test("uses the same Ajv instance for supplemental confirmation, request, and variant constraints", () => {
    expect(SUPPLEMENTAL_SCHEMA_NAMES).toEqual(["confirmation", "request", "resume-variants"]);
    for (const name of SUPPLEMENTAL_SCHEMA_NAMES) {
      const schema = loadSchema(name);
      expect(schema).toBe(AUTHORITATIVE_SCHEMAS[name]);
      expect(schema.$schema).toBe("https://json-schema.org/draft/2020-12/schema");
    }
    const receipt = {
      schema_version: 1,
      run_id: "run.synthetic",
      evidence_id: "evidence.synthetic",
      claim_digest: `sha256:${"0".repeat(64)}`,
      disclosure_audience: "hiring_team",
      disclosure_purpose: "Synthetic targeted application",
      output_mode: "targeted_application",
      reason_codes: ["p2_disclosure"],
      confirmed: true,
      confirmed_by: "interactive_user",
      confirmed_at: "2026-08-21T12:00:00Z",
      nonce: "nonce.synthetic",
    };
    expect(validateSchemaDocument(receipt, "confirmation")).toEqual(receipt);
    expect(() => validateSchemaDocument({
      ...receipt,
      confirmed_at: "not-a-date",
    }, "confirmation")).toThrow(SchemaValidationError);
    expect(() => validateSchemaDocument({
      ...receipt,
      confirmed_by: "automation",
    }, "confirmation")).toThrow(SchemaValidationError);
    const request = Object.freeze({
      source_root: "/private/source",
      output_root: "/private/output",
    });
    const normalized: JsonObject = validateSchemaDocument(request, "request");
    expect(normalized).toEqual({
      schema_version: 1,
      source_root: "/private/source",
      source_adapter: "markdown-career-v1",
      application_constraints: {},
      experience_duration_diagnostics: [],
      output_mode: "targeted_application",
      language: "zh-CN",
      include_extended_profile: false,
      template: "adaptive",
      persist_role_research: false,
      export_roadmap_handoff: false,
      refresh_external_sources: false,
      output_root: "/private/output",
    });
    expect(request).toEqual({
      source_root: "/private/source",
      output_root: "/private/output",
    });
    expect(() => validateSchemaDocument({
      source_root: "/private/source",
      output_root: "/private/output",
      jd: { url: "not a URI" },
    }, "request")).toThrow(SchemaValidationError);
    expect(() => validateSchemaDocument({
      schema_version: 1,
      variants: [],
    }, "resume-variants")).toThrow(SchemaValidationError);
  });

  test("returns deeply frozen normalized clones without mutating canonical callers", () => {
    for (const name of SCHEMA_NAMES) {
      const document = ACCEPTED_DOCUMENTS[name];
      const keysBefore = Object.keys(document);
      const normalized = validateSchemaDocument(document, name);
      expect(normalized).not.toBe(document);
      for (const [key, value] of Object.entries(document)) {
        expect(normalized[key]).toEqual(value);
      }
      expect(Object.isFrozen(normalized)).toBe(true);
      expect(Object.keys(document)).toEqual(keysBefore);
    }
  });

  test("enforces closed objects, constants, enums, and hash patterns", () => {
    expect(() => validateSchemaDocument({
      input_id: "role.synthetic",
      unexpected: true,
    }, "normalized-role-input")).toThrow(SchemaValidationError);

    try {
      validateSchemaDocument({ input_id: "role.synthetic", domain: "company" }, "normalized-role-input");
      throw new Error("expected invalid role domain to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(SchemaValidationError);
      if (!(error instanceof SchemaValidationError)) throw error;
      expect(error.schema).toBe("normalized-role-input");
      expect(error.issues.some((issue) => issue.keyword === "const" && issue.instancePath === "/domain")).toBe(true);
    }

    expect(() => validateSchemaDocument({
      documents: [{
        document_id: "doc.synthetic",
        path: "notes/synthetic.md",
        source_hash: "sha256:ABC",
      }],
    }, "source-map")).toThrow(SchemaValidationError);
  });

  test("keeps expressible path and conditional contracts in Draft 2020-12 schemas", () => {
    const roleSchema = loadSchema("normalized-role-input");
    const reviewSchema = loadSchema("review-decision");
    const approvedSchema = loadSchema("approved-claims");
    expect(JSON.stringify(roleSchema)).toContain("\"if\"");
    expect(JSON.stringify(reviewSchema)).toContain("\"then\"");
    expect(JSON.stringify(approvedSchema)).toContain("\"else\"");

    const confirmedExtractive = {
      claims: [{
        claim_id: "claim.confirmed-extractive",
        origin_evidence_ids: ["evidence.synthetic"],
        approved_safe_claim: "Confirmed synthetic application detail.",
        approval_basis: "user_confirmed",
        reviewer_decision_ids: ["review.privacy.synthetic"],
        claim_mode: "extractive",
        disclosure_decision: "allowed",
        disclosure_audience: "recruiter",
        disclosure_purpose: "Confirmed synthetic application",
      }],
    };
    const normalizedConfirmed = validateSchemaDocument(confirmedExtractive, "approved-claims");
    expect(normalizedConfirmed).toMatchObject({ ...confirmedExtractive, schema_version: 1 });
    expect(Object.isFrozen(normalizedConfirmed)).toBe(true);
    expect(Object.isFrozen(normalizedConfirmed.claims)).toBe(true);
    expect(Object.isFrozen(normalizedConfirmed.claims[0])).toBe(true);
    expect(normalizedConfirmed).not.toBe(confirmedExtractive);
    expect(confirmedExtractive).not.toHaveProperty("schema_version");

    const requirementReview = {
      decisions: [{
        review_id: "review.requirement.synthetic",
        evidence_id: "requirement.synthetic",
        reviewer_id: "reviewer.synthetic",
        review_kind: "requirement",
        outcome: "approve",
        reasoning: "Synthetic requirement classification.",
      }],
    };
    expect(validateSchemaDocument(requirementReview, "review-decision")).toMatchObject({
      schema_version: 1,
      decisions: [{
        approved_safe_claim: null,
        review_kind: "requirement",
        outcome: "approve",
      }],
    });
    expect(requirementReview.decisions[0]).not.toHaveProperty("approved_safe_claim");
    expect(validateSchemaDocument({
      decisions: [{
        review_id: "review.evidence.bound",
        evidence_id: "evidence.synthetic",
        reviewer_id: "reviewer.synthetic",
        review_kind: "evidence",
        outcome: "approve",
        reasoning: "Synthetic evidence approval.",
        approved_safe_claim: "Bound synthetic claim.",
      }],
    }, "review-decision")).toMatchObject({
      decisions: [{ approved_safe_claim: "Bound synthetic claim." }],
    });

    const invalidDocuments: readonly [SchemaName, JsonObject][] = [
      ["normalized-role-input", {
        input_id: "role.explicit-missing-source",
        requirements: [{
          requirement_id: "requirement.synthetic",
          text: "Synthetic requirement",
          origin: "explicit",
          confidence: 0.5,
          reasoning: "Source intentionally omitted.",
        }],
      }],
      ["review-decision", {
        decisions: [{
          review_id: "review.privacy",
          evidence_id: "evidence.synthetic",
          reviewer_id: "reviewer.synthetic",
          review_kind: "privacy",
          outcome: "approve",
          reasoning: "Audience and purpose intentionally omitted.",
          disclosure_decision: "allowed",
        }],
      }],
      ["approved-claims", {
        claims: [{
          claim_id: "claim.invalid-basis",
          origin_evidence_ids: ["evidence.synthetic"],
          approved_safe_claim: "Synthetic semantic rewrite.",
          approval_basis: "mechanical",
          claim_mode: "reviewed-semantic",
          disclosure_decision: "allowed",
          disclosure_audience: "recruiter",
          disclosure_purpose: "Synthetic screening",
        }],
      }],
      ["approved-claims", {
        claims: [{
          claim_id: "claim.confirmed-without-review",
          origin_evidence_ids: ["evidence.synthetic"],
          approved_safe_claim: "Confirmed synthetic application detail.",
          approval_basis: "user_confirmed",
          claim_mode: "extractive",
          disclosure_decision: "allowed",
          disclosure_audience: "recruiter",
          disclosure_purpose: "Confirmed synthetic application",
        }],
      }],
      ["source-map", {
        documents: [{
          document_id: "doc.noncanonical",
          path: "notes//synthetic.md",
          source_hash: `sha256:${"0".repeat(64)}`,
        }],
      }],
    ];

    for (const [name, document] of invalidDocuments) {
      try {
        validateSchemaDocument(document, name);
        throw new Error(`expected ${name} conditional contract to fail`);
      } catch (error) {
        expect(error).toBeInstanceOf(SchemaValidationError);
        if (!(error instanceof SchemaValidationError)) throw error;
        expect(error.issues.some((item) => item.schemaPath.startsWith("#/x-canonical-contract/"))).toBe(false);
      }
    }
  });

  test("uses post-Ajv checks only for cross-field ordering and keyed relational invariants", () => {
    try {
      validateSchemaDocument({
        documents: [{
          document_id: "doc.bad-span",
          path: "notes/bad-span.md",
          source_hash: `sha256:${"0".repeat(64)}`,
          span: { start_line: 2, end_line: 1, start_byte: 4, end_byte: 4 },
        }],
      }, "source-map");
      throw new Error("expected ordered source span to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(SchemaValidationError);
      if (!(error instanceof SchemaValidationError)) throw error;
      expect(error.issues.filter((item) => item.keyword === "span-order")).toHaveLength(2);
      expect(error.issues.filter((item) => item.keyword === "span-order").every(
        (item) => item.schemaPath.startsWith("#/x-canonical-contract/"),
      )).toBe(true);
    }

    try {
      validateSchemaDocument({
        input_id: "evidence.duplicates",
        candidates: [
          {
            evidence_id: "evidence.same",
            source: {
              path: "notes/evidence.md",
              source_hash: `sha256:${"0".repeat(64)}`,
              span: { start_line: 1, end_line: 1, start_byte: 0, end_byte: 1 },
              exact_quote: "_",
            },
            proposed_claim: "_",
            confidence: 1,
            reasoning: "First synthetic candidate.",
          },
          {
            evidence_id: "evidence.same",
            source: {
              path: "notes/evidence.md",
              source_hash: `sha256:${"0".repeat(64)}`,
              span: { start_line: 1, end_line: 1, start_byte: 0, end_byte: 1 },
              exact_quote: "_",
            },
            proposed_claim: "_",
            confidence: 1,
            reasoning: "Second synthetic candidate.",
          },
        ],
      }, "normalized-evidence-input");
      throw new Error("expected duplicate evidence ID to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(SchemaValidationError);
      if (!(error instanceof SchemaValidationError)) throw error;
      expect(error.issues).toContainEqual(expect.objectContaining({
        keyword: "duplicate-evidence-id",
        schemaPath: "#/x-canonical-contract/duplicate-evidence-id",
      }));
    }
  });

  test("rejects source-body-shaped fields at any depth without retaining their value in errors", () => {
    const privateSentinel = "PRIVATE-SOURCE-BODY-SENTINEL";
    try {
      validateSchemaDocument({
        input_id: "evidence.synthetic",
        candidates: [{ source_content: privateSentinel }],
      }, "normalized-evidence-input");
      throw new Error("expected source body field to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(SchemaValidationError);
      if (!(error instanceof SchemaValidationError)) throw error;
      expect(error.issues).toEqual([expect.objectContaining({
        instancePath: "/candidates/0/source_content",
        keyword: "forbiddenSourceBody",
      })]);
      expect(JSON.stringify(error.toJSON())).not.toContain(privateSentinel);
    }
  });

  test("returns stable structured issues and rejects unknown schema names", () => {
    try {
      validateSchemaDocument({ input_id: "", extra: true }, "normalized-role-input");
      throw new Error("expected invalid document to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(SchemaValidationError);
      if (!(error instanceof SchemaValidationError)) throw error;
      expect(error.toJSON()).toEqual(expect.objectContaining({
        name: "SchemaValidationError",
        code: "SCHEMA_VALIDATION_FAILED",
        schema: "normalized-role-input",
      }));
      expect(error.issues.length).toBeGreaterThanOrEqual(2);
      expect([...error.issues]).toEqual([...error.issues].sort((left, right) => (
        left.instancePath.localeCompare(right.instancePath)
        || left.schemaPath.localeCompare(right.schemaPath)
        || left.keyword.localeCompare(right.keyword)
        || left.message.localeCompare(right.message)
      )));
    }

    expect(() => schemaName("evidence-map.schema.json")).toThrow(SchemaConfigurationError);
  });
});
