import { createRequire } from 'node:module';
import path from 'node:path';
import { expect } from 'vitest';

// Shared by the contract conformance tests: loads contracts/code-adapter.openapi.yaml and checks values against it.

const require = createRequire(import.meta.url);
const SwaggerParser = require('@apidevtools/swagger-parser');
const Ajv = require('ajv').default ?? require('ajv');
const addFormats = require('ajv-formats').default ?? require('ajv-formats');

export interface Schema {
  type?: string;
  properties?: Record<string, Schema>;
  items?: Schema;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  default?: unknown;
  [key: string]: unknown;
}

export interface Doc {
  paths: Record<string, Record<string, any>>;
  components: { schemas: Record<string, Schema> };
}

const CONTRACT = path.resolve(import.meta.dirname, '../../contracts/code-adapter.openapi.yaml');
const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);

/** The contract with every $ref resolved. */
export async function loadContract(): Promise<Doc> {
  return (await SwaggerParser.dereference(CONTRACT)) as Doc;
}

export function responseSchema(doc: Doc, pathName: string, method: string, status: number, contentType = 'application/json'): Schema {
  const response = doc.paths[pathName]?.[method]?.responses?.[String(status)];
  const schema = response?.content?.[contentType]?.schema as Schema | undefined;
  if (!schema) throw new Error(`The contract has no ${contentType} schema for ${method} ${pathName} ${status}`);
  return schema;
}

export const declaredStatuses = (doc: Doc, pathName: string, method: string): string[] =>
  Object.keys(doc.paths[pathName]?.[method]?.responses ?? {});

/** Keys present in `value` that the schema does not list. Ajv allows extra keys, so this catches undocumented fields. */
export function undocumented(schema: Schema, value: unknown, at = '$'): string[] {
  if (Array.isArray(value)) return value.flatMap((v, i) => (schema.items ? undocumented(schema.items, v, `${at}[${i}]`) : []));
  if (value === null || typeof value !== 'object' || !schema.properties) return [];
  const out: string[] = [];
  for (const [key, v] of Object.entries(value as Record<string, unknown>)) {
    const sub = schema.properties[key];
    if (!sub) out.push(`${at}.${key}`);
    else out.push(...undocumented(sub, v, `${at}.${key}`));
  }
  return out;
}

/** The value must satisfy the schema and use no field the schema does not document. */
export function conforms(schema: Schema, value: unknown): void {
  const validate = ajv.compile(schema);
  const ok = validate(value);
  expect(ok ? [] : validate.errors, JSON.stringify(value).slice(0, 400)).toEqual([]);
  expect(undocumented(schema, value), 'fields the contract does not document').toEqual([]);
}
