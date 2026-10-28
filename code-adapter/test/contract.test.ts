import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ProblemError } from '../src/errors.js';
import { buildServer } from '../src/server.js';
import { validateCodeQuery } from '../src/validate.js';
import { conforms, declaredStatuses, type Doc, loadContract, responseSchema as responseSchemaOf, type Schema } from './contract-helpers.js';
import {
  commitShaFor,
  ORG_A_FILES,
  seedProject,
  signedEnvelope,
  testConfig,
} from './helpers.js';

// Conformance: real responses are checked against the schemas in contracts/code-adapter.openapi.yaml, and the
// contract and the code are compared in both directions so neither can drift without a test failing.
// The job endpoints are covered in contract.jobs.test.ts.

let doc: Doc;
let app: FastifyInstance;
let dataDir: string;

beforeAll(async () => {
  doc = await loadContract();
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-contract-'));
  await seedProject(dataDir, 'orgA', 'p1', ORG_A_FILES);
  app = buildServer(testConfig(dataDir), { commitSha: commitShaFor });
  await app.ready();
}, 180_000);

afterAll(async () => {
  await app.close();
  fs.rmSync(dataDir, { recursive: true, force: true });
});

const responseSchema = (pathName: string, method: string, status: number, contentType?: string): Schema =>
  responseSchemaOf(doc, pathName, method, status, contentType);

const get = (url: string, org = 'orgA', project = 'p1', scopes?: string[]) =>
  app.inject({ method: 'GET', url, headers: { 'x-astra-envelope': signedEnvelope(org, project, scopes) } });
const post = (body: unknown, org = 'orgA', project = 'p1', scopes?: string[]) =>
  app.inject({
    method: 'POST',
    url: '/internal/v1/code/query',
    headers: { 'x-astra-envelope': signedEnvelope(org, project, scopes) },
    payload: body as object,
  });

describe('real responses match the contract', () => {
  const querySchema = () => responseSchema('/internal/v1/code/query', 'post', 200);

  it.each([
    ['callers, exact symbol', { mode: 'callers', symbols: ['render'], depth: 5 }],
    ['impact', { mode: 'impact', symbols: ['render'], depth: 2 }],
    ['lookup by symbol and keyword', { mode: 'lookup', symbols: ['handle'], keywords: ['token'] }],
    ['lookup, ambiguous symbol', { mode: 'lookup', symbols: ['draw'] }],
    ['callers, ambiguous symbol (refused)', { mode: 'callers', symbols: ['draw'] }],
    ['callers, unknown symbol', { mode: 'callers', symbols: ['NoSuchFunction'] }],
    ['callers, no text', { mode: 'callers', symbols: ['render'], include_code: false }],
    ['lookup, fallback origin', { mode: 'lookup', keywords: ['token'], fallback_origin: 'analyzer' }],
    ['callers, file-qualified symbol', { mode: 'callers', symbols: ['web/app.ts::render'] }],
  ])('POST query: %s', async (_name, body) => {
    const res = await post(body);
    expect(res.statusCode).toBe(200);
    conforms(querySchema(), res.json());
  });

  it('POST query: project not indexed', async () => {
    const res = await post({ mode: 'callers', symbols: ['render'] }, 'orgA', 'p2');
    expect(res.statusCode).toBe(200);
    expect(res.json().plane_status).toBe('not_ready');
    conforms(querySchema(), res.json());
  });

  it('GET status: ready and not indexed', async () => {
    const schema = responseSchema('/internal/v1/code/status', 'get', 200);
    const ready = await get('/internal/v1/code/status');
    expect(ready.json().state).toBe('ready');
    conforms(schema, ready.json());
    const none = await get('/internal/v1/code/status', 'orgA', 'p2');
    expect(none.json().state).toBe('not_indexed');
    conforms(schema, none.json());
  });

  it('GET health', async () => {
    const res = await app.inject({ method: 'GET', url: '/internal/v1/health' });
    conforms(responseSchema('/internal/v1/health', 'get', 200), res.json());
  });

  it.each([
    ['401 no envelope', () => app.inject({ method: 'POST', url: '/internal/v1/code/query', payload: { mode: 'lookup', keywords: ['a'] } }), 401, '/internal/v1/code/query', 'post'],
    ['403 wrong scope', () => post({ mode: 'lookup', keywords: ['a'] }, 'orgA', 'p1', ['code:sync']), 403, '/internal/v1/code/query', 'post'],
    ['422 unknown field', () => post({ mode: 'lookup', keywords: ['a'], org_id: 'x' }), 422, '/internal/v1/code/query', 'post'],
    ['422 mode rule', () => post({ mode: 'callers', symbols: ['a', 'b'] }), 422, '/internal/v1/code/query', 'post'],
    ['422 path refused', () => post({ mode: 'lookup', keywords: ['a'], path_prefix: '../x' }), 422, '/internal/v1/code/query', 'post'],
    ['422 malformed JSON', () => app.inject({ method: 'POST', url: '/internal/v1/code/query', headers: { 'x-astra-envelope': signedEnvelope('orgA', 'p1'), 'content-type': 'application/json' }, payload: '{nope' }), 422, '/internal/v1/code/query', 'post'],
    ['401 status without envelope', () => app.inject({ method: 'GET', url: '/internal/v1/code/status' }), 401, '/internal/v1/code/status', 'get'],
    ['403 status wrong scope', () => get('/internal/v1/code/status', 'orgA', 'p1', ['code:sync']), 403, '/internal/v1/code/status', 'get'],
  ] as const)('error responses are problem+json: %s', async (_name, call, status, pathName, method) => {
    const res = await call();
    expect(res.statusCode).toBe(status);
    expect(res.headers['content-type']).toContain('application/problem+json');
    // The contract must declare this status for this operation, and the body must match the Problem schema.
    expect(declaredStatuses(doc, pathName, method), `${method} ${pathName} declares ${status}`).toContain(String(status));
    conforms(doc.components.schemas.Problem as Schema, res.json());
  });
});

describe('the contract and the code agree', () => {
  const requestSchema = () => doc.components.schemas.CodeQueryRequest as Schema;
  const properties = () => requestSchema().properties as Record<string, Schema>;

  /** One valid value per contract property. A property added to the contract must be added here too. */
  const SAMPLE: Record<string, unknown> = {
    mode: 'lookup',
    symbols: ['a'],
    keywords: ['k'],
    path_prefix: 'src',
    depth: 2,
    limit: 5,
    include_code: false,
    max_code_chars: 100,
    fallback_origin: 'analyzer',
  };

  function accepted(body: unknown): boolean {
    try {
      validateCodeQuery(body);
      return true;
    } catch (e) {
      if (e instanceof ProblemError) return false;
      throw e;
    }
  }
  const errorOf = (body: unknown): ProblemError | undefined => {
    try {
      validateCodeQuery(body);
    } catch (e) {
      if (e instanceof ProblemError) return e;
      throw e;
    }
    return undefined;
  };

  it("accepts the contract's own request examples", () => {
    const examples = doc.paths['/internal/v1/code/query']!.post.requestBody.content['application/json'].examples as Record<string, { value: unknown }>;
    expect(Object.keys(examples).length).toBeGreaterThan(0);
    for (const [name, ex] of Object.entries(examples)) {
      expect(accepted(ex.value), `example ${name}`).toBe(true);
    }
  });

  it('knows every request property in the contract, and rejects ones the contract lacks', () => {
    expect(Object.keys(properties()).sort()).toEqual(Object.keys(SAMPLE).sort());
    for (const [field, value] of Object.entries(SAMPLE)) {
      expect(accepted({ mode: 'lookup', keywords: ['k'], [field]: value }), `property ${field}`).toBe(true);
    }
    const undocumentedField = errorOf({ mode: 'lookup', keywords: ['k'], not_in_contract: 1 });
    expect(undocumentedField?.errorCode).toBe('invalid_field');
  });

  it('accepts every mode in the contract and no other', () => {
    const modes = properties().mode!.enum as string[];
    const bodies: Record<string, unknown> = {
      lookup: { mode: 'lookup', keywords: ['k'] },
      flow: { mode: 'flow', symbols: ['a', 'b'] },
      callers: { mode: 'callers', symbols: ['a'] },
      impact: { mode: 'impact', symbols: ['a'] },
    };
    expect(modes.sort()).toEqual(Object.keys(bodies).sort());
    for (const m of modes) expect(accepted(bodies[m]), m).toBe(true);
    expect(errorOf({ mode: 'explore', keywords: ['k'] })?.field).toBe('mode');
  });

  it('enforces the numeric bounds the contract states', () => {
    for (const field of ['depth', 'limit', 'max_code_chars']) {
      const { minimum, maximum } = properties()[field]!;
      expect(typeof minimum, `${field} has a minimum`).toBe('number');
      expect(typeof maximum, `${field} has a maximum`).toBe('number');
      const base = { mode: 'callers', symbols: ['a'] };
      expect(accepted({ ...base, [field]: minimum }), `${field} = min`).toBe(true);
      expect(accepted({ ...base, [field]: maximum }), `${field} = max`).toBe(true);
      expect(errorOf({ ...base, [field]: (minimum as number) - 1 })?.field, `${field} below min`).toBe(field);
      expect(errorOf({ ...base, [field]: (maximum as number) + 1 })?.field, `${field} above max`).toBe(field);
    }
  });

  it('applies the defaults the contract states', () => {
    const q = validateCodeQuery({ mode: 'lookup', keywords: ['k'] });
    expect(q.limit).toBe(properties().limit!.default);
    expect(q.includeCode).toBe(properties().include_code!.default);
    expect(q.maxCodeChars).toBe(properties().max_code_chars!.default);
    expect(q.fallbackOrigin).toBe(properties().fallback_origin!.default);
  });

  it('limits array sizes and string lengths as the contract states', () => {
    const symbols = properties().symbols as Schema & { maxItems: number; items: { maxLength: number } };
    expect(accepted({ mode: 'lookup', symbols: Array.from({ length: symbols.maxItems }, (_, i) => `s${i}`) })).toBe(true);
    expect(accepted({ mode: 'lookup', symbols: Array.from({ length: symbols.maxItems + 1 }, (_, i) => `s${i}`) })).toBe(false);
    expect(accepted({ mode: 'lookup', symbols: ['x'.repeat(symbols.items.maxLength)] })).toBe(true);
    expect(accepted({ mode: 'lookup', symbols: ['x'.repeat(symbols.items.maxLength + 1)] })).toBe(false);
    const keywords = properties().keywords as Schema & { maxItems: number; items: { maxLength: number } };
    expect(accepted({ mode: 'lookup', keywords: ['k'.repeat(keywords.items.maxLength)] })).toBe(true);
    expect(accepted({ mode: 'lookup', keywords: ['k'.repeat(keywords.items.maxLength + 1)] })).toBe(false);
  });

  it('lists exactly the error codes the code can raise', () => {
    const source = fs.readFileSync(path.resolve(import.meta.dirname, '../src/errors.ts'), 'utf8');
    const union = /export type ErrorCode =([^;]+);/.exec(source)?.[1] ?? '';
    const inCode = [...union.matchAll(/'([a-z_]+)'/g)].map((m) => m[1]!).sort();
    const inContract = [...((doc.components.schemas.Problem!.properties!.error_code as Schema).enum as string[])].sort();
    expect(inCode.length).toBeGreaterThan(5);
    expect(inContract).toEqual(inCode);
  });

  it('declares the plane_status and index_state values the code can return', () => {
    const planeStatus = (doc.components.schemas.CodeQueryResponse!.properties!.plane_status as Schema).enum as string[];
    expect([...planeStatus].sort()).toEqual(['degraded', 'not_ready', 'ok']);
    const indexState = (doc.components.schemas.Snapshot!.properties!.index_state as Schema).enum as string[];
    expect([...indexState].sort()).toEqual(['complete', 'failed', 'indexing', 'not_indexed', 'partial']);
  });
});
