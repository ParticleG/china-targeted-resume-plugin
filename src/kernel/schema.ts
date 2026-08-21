import Ajv2020 from "ajv/dist/2020.js";
import type {
  AnySchemaObject,
  ErrorObject,
  ValidateFunction,
} from "ajv";
import addFormats from "ajv-formats";
import { readFileSync } from "node:fs";
import { canonicalContractIssues } from "./schema-contracts.ts";

/** The five proof-carrying IR schema authorities used for parity fixtures. */
export const SCHEMA_NAMES = [
  "source-map",
  "normalized-role-input",
  "normalized-evidence-input",
  "review-decision",
  "approved-claims",
] as const;

/** Additional deterministic constraints consumed by the TypeScript kernel. */
export const SUPPLEMENTAL_SCHEMA_NAMES = [
  "confirmation",
  "request",
  "resume-variants",
] as const;
export const KERNEL_SCHEMA_NAMES = [
  ...SCHEMA_NAMES,
  ...SUPPLEMENTAL_SCHEMA_NAMES,
] as const;

export type SchemaName = (typeof SCHEMA_NAMES)[number];
export type SupplementalSchemaName = (typeof SUPPLEMENTAL_SCHEMA_NAMES)[number];
export type KernelSchemaName = (typeof KERNEL_SCHEMA_NAMES)[number];
export type SchemaSpecifier =
  | KernelSchemaName
  | `${KernelSchemaName}.json`
  | `${KernelSchemaName}.schema.json`;

export type JsonPrimitive = null | boolean | number | string;
export type JsonValue = JsonPrimitive | JsonObject | JsonArray;
export interface JsonObject {
  readonly [key: string]: JsonValue;
}
export interface JsonArray extends ReadonlyArray<JsonValue> {}

export interface SchemaValidationIssue {
  readonly instancePath: string;
  readonly schemaPath: string;
  readonly keyword: string;
  readonly message: string;
  readonly parameters: Readonly<Record<string, unknown>>;
}

export interface SerializedSchemaValidationError {
  readonly name: "SchemaValidationError";
  readonly code: "SCHEMA_VALIDATION_FAILED";
  readonly schema: KernelSchemaName;
  readonly message: string;
  readonly issues: readonly SchemaValidationIssue[];
}

export interface SerializedSchemaConfigurationError {
  readonly name: "SchemaConfigurationError";
  readonly code: "SCHEMA_CONFIGURATION_FAILED";
  readonly message: string;
  readonly schema?: KernelSchemaName;
}

export class SchemaValidationError extends Error {
  override readonly name = "SchemaValidationError";
  readonly code = "SCHEMA_VALIDATION_FAILED";
  readonly schema: KernelSchemaName;
  readonly issues: readonly SchemaValidationIssue[];

  constructor(schema: KernelSchemaName, issues: readonly SchemaValidationIssue[]) {
    const stableIssues = Object.freeze([...issues]);
    const summary = stableIssues
      .map((issue) => `${issue.instancePath || "$root"}: ${issue.message}`)
      .join("; ");
    super(`${schema} schema validation failed${summary ? `: ${summary}` : ""}`);
    this.schema = schema;
    this.issues = stableIssues;
  }

  toJSON(): SerializedSchemaValidationError {
    return Object.freeze({
      name: this.name,
      code: this.code,
      schema: this.schema,
      message: this.message,
      issues: this.issues,
    });
  }
}

export class SchemaConfigurationError extends Error {
  override readonly name = "SchemaConfigurationError";
  readonly code = "SCHEMA_CONFIGURATION_FAILED";
  readonly schema?: KernelSchemaName;

  constructor(message: string, options: { readonly schema?: KernelSchemaName; readonly cause?: unknown } = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    if (options.schema !== undefined) this.schema = options.schema;
  }

  toJSON(): SerializedSchemaConfigurationError {
    const schema = this.schema;
    return Object.freeze({
      name: this.name,
      code: this.code,
      message: this.message,
      ...(schema === undefined ? {} : { schema }),
    });
  }
}

const BODY_KEYS: Readonly<Record<string, true>> = Object.freeze({
  body: true,
  content: true,
  document_body: true,
  raw_source: true,
  source_body: true,
  source_content: true,
  source_text: true,
  whole_source: true,
});

function isIrSchemaName(value: string): value is SchemaName {
  return SCHEMA_NAMES.some((name) => name === value);
}

function isKernelSchemaName(value: string): value is KernelSchemaName {
  return KERNEL_SCHEMA_NAMES.some((name) => name === value);
}

export function schemaName(specifier: SchemaSpecifier | string): KernelSchemaName {
  const normalized = specifier.endsWith(".schema.json")
    ? specifier.slice(0, -".schema.json".length)
    : specifier.endsWith(".json")
      ? specifier.slice(0, -".json".length)
      : specifier;
  if (!isKernelSchemaName(normalized)) {
    throw new SchemaConfigurationError(
      `Unknown kernel schema ${JSON.stringify(normalized)}; expected one of ${KERNEL_SCHEMA_NAMES.join(", ")}`,
    );
  }
  return normalized;
}

function isPlainObject(value: object): value is Record<string, unknown> {
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isJsonArray(value: JsonValue): value is JsonArray {
  return Array.isArray(value);
}

function pointerToken(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function compatibilityIssue(instancePath: string, message: string): SchemaValidationIssue {
  return Object.freeze({
    instancePath,
    schemaPath: "#",
    keyword: "jsonType",
    message,
    parameters: Object.freeze({}),
  });
}

function assertJsonValue(
  value: unknown,
  instancePath: string,
  ancestors: Set<object>,
): asserts value is JsonValue {
  if (
    value === null
    || typeof value === "string"
    || typeof value === "boolean"
  ) return;
  if (typeof value === "number") {
    if (Number.isFinite(value)) return;
    throw new SchemaValidationError("source-map", [
      compatibilityIssue(instancePath, "must be a finite JSON number"),
    ]);
  }
  if (typeof value !== "object") {
    throw new SchemaValidationError("source-map", [
      compatibilityIssue(instancePath, "must be JSON-compatible"),
    ]);
  }
  if (ancestors.has(value)) {
    throw new SchemaValidationError("source-map", [
      compatibilityIssue(instancePath, "must not contain a reference cycle"),
    ]);
  }
  if (!Array.isArray(value) && !isPlainObject(value)) {
    throw new SchemaValidationError("source-map", [
      compatibilityIssue(instancePath, "must be a plain JSON object or array"),
    ]);
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      for (const [index, nested] of value.entries()) {
        assertJsonValue(nested, `${instancePath}/${index}`, ancestors);
      }
      return;
    }
    for (const [key, nested] of Object.entries(value)) {
      assertJsonValue(nested, `${instancePath}/${pointerToken(key)}`, ancestors);
    }
  } finally {
    ancestors.delete(value);
  }
}

function rejectSourceBodies(value: JsonValue, instancePath = "", ancestors = new Set<object>()): void {
  if (value === null || typeof value !== "object") return;
  if (ancestors.has(value)) return;
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      for (const [index, nested] of value.entries()) {
        rejectSourceBodies(nested, `${instancePath}/${index}`, ancestors);
      }
      return;
    }
    for (const [key, nested] of Object.entries(value)) {
      const nestedPath = `${instancePath}/${pointerToken(key)}`;
      if (BODY_KEYS[key.toLowerCase()] === true) {
        throw new SchemaValidationError("source-map", [Object.freeze({
          instancePath: nestedPath,
          schemaPath: "#/privacy/source-body-fields",
          keyword: "forbiddenSourceBody",
          message: "source-body-shaped fields are forbidden; retain only metadata and exact per-proposal quotes",
          parameters: Object.freeze({ key }),
        })]);
      }
      rejectSourceBodies(nested, nestedPath, ancestors);
    }
  } finally {
    ancestors.delete(value);
  }
}

function deepFreeze(value: JsonValue): JsonValue {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    for (const nested of Object.values(value)) deepFreeze(nested);
    Object.freeze(value);
  }
  return value;
}

function loadSchemaFile(name: KernelSchemaName): JsonObject {
  const url = new URL(`../../schemas/${name}.schema.json`, import.meta.url);
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(url, "utf8"));
  } catch (cause) {
    throw new SchemaConfigurationError(`Could not load authoritative kernel schema ${name}`, {
      schema: name,
      cause,
    });
  }
  try {
    assertJsonValue(parsed, "", new Set());
  } catch (cause) {
    throw new SchemaConfigurationError(`Authoritative kernel schema ${name} is not a JSON object`, {
      schema: name,
      cause,
    });
  }
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new SchemaConfigurationError(`Authoritative kernel schema ${name} must be a JSON object`, {
      schema: name,
    });
  }
  return deepFreeze(parsed) as JsonObject;
}

const schemas = Object.freeze(Object.fromEntries(
  KERNEL_SCHEMA_NAMES.map((name) => [name, loadSchemaFile(name)]),
) as Record<KernelSchemaName, JsonObject>);

const ajv = new Ajv2020({
  allErrors: true,
  coerceTypes: false,
  messages: true,
  removeAdditional: false,
  strict: true,
  // Composed schemas declare property types in referenced/allOf parents; Ajv
  // cannot infer those declarations for type-specific child constraints.
  strictTypes: false,
  // resume-variants deliberately models a required pair plus an optional third
  // tuple element (minItems 2, maxItems/prefixItems 3).
  strictTuples: false,
  useDefaults: true,
  validateFormats: true,
});
addFormats(ajv, { mode: "full" });

const validators = Object.freeze(Object.fromEntries(KERNEL_SCHEMA_NAMES.map((name) => {
  try {
    const schema = schemas[name] as AnySchemaObject;
    ajv.addSchema(schema, name);
    const validator = ajv.getSchema(name);
    if (validator === undefined) {
      throw new Error("Ajv did not return a validator after schema registration");
    }
    return [name, validator] as const;
  } catch (cause) {
    throw new SchemaConfigurationError(`Could not compile authoritative kernel schema ${name}`, {
      schema: name,
      cause,
    });
  }
})) as Record<KernelSchemaName, ValidateFunction>);

export const AUTHORITATIVE_SCHEMAS: Readonly<Record<KernelSchemaName, JsonObject>> = schemas;

export function loadSchema(specifier: SchemaSpecifier | string): JsonObject {
  return schemas[schemaName(specifier)];
}

function stableIssue(error: ErrorObject): SchemaValidationIssue {
  return Object.freeze({
    instancePath: error.instancePath,
    schemaPath: error.schemaPath,
    keyword: error.keyword,
    message: error.message ?? "is invalid",
    parameters: Object.freeze({ ...error.params }),
  });
}

function compareText(left: string, right: string): number {
  const leftIterator = left[Symbol.iterator]();
  const rightIterator = right[Symbol.iterator]();
  while (true) {
    const leftPart = leftIterator.next();
    const rightPart = rightIterator.next();
    if (leftPart.done || rightPart.done) {
      if (leftPart.done && rightPart.done) return 0;
      return leftPart.done ? -1 : 1;
    }
    const difference = (leftPart.value.codePointAt(0) ?? 0) - (rightPart.value.codePointAt(0) ?? 0);
    if (difference !== 0) return difference;
  }
}

function compareIssues(left: SchemaValidationIssue, right: SchemaValidationIssue): number {
  return compareText(left.instancePath, right.instancePath)
    || compareText(left.schemaPath, right.schemaPath)
    || compareText(left.keyword, right.keyword)
    || compareText(left.message, right.message);
}

/**
 * Validate and normalize an isolated JSON clone, apply schema-declared
 * defaults, and return a deeply frozen document. Caller input is never mutated.
 */
export function validateSchemaDocument<TValue extends JsonObject>(
  value: TValue,
  specifier: SchemaSpecifier | string,
): TValue;
export function validateSchemaDocument(
  value: unknown,
  specifier: SchemaSpecifier | string,
): JsonObject;
export function validateSchemaDocument(
  value: unknown,
  specifier: SchemaSpecifier | string,
): JsonObject {
  const name = schemaName(specifier);
  try {
    assertJsonValue(value, "", new Set());
  } catch (error) {
    if (error instanceof SchemaValidationError) {
      throw new SchemaValidationError(name, error.issues);
    }
    throw error;
  }
  try {
    rejectSourceBodies(value);
  } catch (error) {
    if (error instanceof SchemaValidationError) {
      throw new SchemaValidationError(name, error.issues);
    }
    throw error;
  }
  if (value === null || isJsonArray(value) || typeof value !== "object") {
    throw new SchemaValidationError(name, [Object.freeze({
      instancePath: "",
      schemaPath: "#/type",
      keyword: "type",
      message: "must be object",
      parameters: Object.freeze({ type: "object" }),
    })]);
  }

  // Ajv's default application is intentionally confined to an isolated JSON
  // clone. Validation and normalization never mutate caller-owned input.
  const normalized = structuredClone(value);
  const validator = validators[name];
  const schemaIssues = validator(normalized) ? [] : (validator.errors ?? []).map(stableIssue);
  try {
    rejectSourceBodies(normalized);
  } catch (error) {
    if (error instanceof SchemaValidationError) {
      throw new SchemaValidationError(name, error.issues);
    }
    throw error;
  }
  const contractIssues = isIrSchemaName(name) ? canonicalContractIssues(name, normalized) : [];
  const issues = [...schemaIssues, ...contractIssues].sort(compareIssues);
  if (issues.length > 0) {
    throw new SchemaValidationError(name, issues);
  }
  return deepFreeze(normalized) as JsonObject;
}
