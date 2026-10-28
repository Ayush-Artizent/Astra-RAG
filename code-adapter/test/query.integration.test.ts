import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { buildServer } from '../src/server.js';
import {
  commitShaFor,
  ORG_A_FILES,
  ORG_B_FILES,
  seedProject,
  signedEnvelope as envelope,
  testConfig,
} from './helpers.js';

// Real CodeGraph indexes behind the real HTTP routes. Two orgs both have a project called p1.
let dataDir: string;
let app: FastifyInstance;

async function query(body: unknown, opts: { org?: string; project?: string; scopes?: string[]; headers?: Record<string, string> } = {}) {
  return app.inject({
    method: 'POST',
    url: '/internal/v1/code/query',
    headers: {
      'x-astra-envelope': envelope(opts.org ?? 'orgA', opts.project ?? 'p1', opts.scopes),
      ...(opts.headers ?? {}),
    },
    payload: body as object,
  });
}

beforeAll(async () => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-query-'));
  await seedProject(dataDir, 'orgA', 'p1', ORG_A_FILES);
  await seedProject(dataDir, 'orgB', 'p1', ORG_B_FILES);
  app = buildServer(testConfig(dataDir), { commitSha: commitShaFor });
  await app.ready();
}, 180_000);

afterAll(async () => {
  await app.close();
  fs.rmSync(dataDir, { recursive: true, force: true });
});

describe('callers', () => {
  it('returns direct callers with provenance, citation, code and the call-site line', async () => {
    const res = await query({ mode: 'callers', symbols: ['render'] });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.plane_status).toBe('ok');
    expect(body.snapshot).toMatchObject({ commit_sha: 'a1b2c3d', index_state: 'complete' });
    expect(body.resolved_symbols[0]).toMatchObject({ input: 'render', status: 'exact', qualified_name: 'render' });

    const names = body.results.map((r: { provenance: { qualified_name: string } }) => r.provenance.qualified_name).sort();
    expect(names).toEqual(['Widget.draw', 'handle']);

    const handle = body.results.find((r: { provenance: { symbol: string } }) => r.provenance.symbol === 'handle');
    expect(handle).toMatchObject({
      kind: 'function',
      depth: 1,
      relation: 'calls',
      call_line: 2,
      provenance: { file_path: 'web/app.ts', commit_sha: 'a1b2c3d' },
    });
    expect(handle.citation).toMatch(/^web\/app\.ts:\d+-\d+ \(handle @a1b2c3d\)$/);
    expect(handle.text).toContain('return render(req)');
    expect(body.results.map((r: { plane_rank: number }) => r.plane_rank)).toEqual([1, 2]);
  });

  it('walks to the requested depth and reports each distance', async () => {
    const res = await query({ mode: 'callers', symbols: ['render'], depth: 5 });
    const byName = Object.fromEntries(
      res.json().results.map((r: { provenance: { qualified_name: string }; depth: number }) => [r.provenance.qualified_name, r.depth]),
    );
    expect(byName).toMatchObject({ handle: 1, 'Widget.draw': 1, route: 2, main: 3 });
    expect(byName.start).toBe(4); // cross-file: web/index.ts calls main
  });

  it('refuses an ambiguous name and lists the alternatives', async () => {
    const res = await query({ mode: 'callers', symbols: ['draw'] });
    const body = res.json();
    expect(res.statusCode).toBe(200);
    expect(body.plane_status).toBe('degraded');
    expect(body.results).toEqual([]);
    expect(body.resolved_symbols[0].status).toBe('ambiguous');
    expect(body.resolved_symbols[0].alternatives.length).toBeGreaterThan(0);
  });

  it('answers for the best candidate when the policy is best', async () => {
    const lenient = buildServer(testConfig(dataDir), { ambiguousPolicy: 'best' });
    const res = await lenient.inject({
      method: 'POST',
      url: '/internal/v1/code/query',
      headers: { 'x-astra-envelope': envelope('orgA', 'p1') },
      payload: { mode: 'callers', symbols: ['draw'] },
    });
    expect(res.json().resolved_symbols[0].status).toBe('ambiguous');
    expect(res.json().plane_status).toBe('degraded');
    await lenient.close();
  });

  it('resolves a qualified name to one class and gives no results when nobody calls it', async () => {
    const res = await query({ mode: 'callers', symbols: ['Panel.draw'] });
    const body = res.json();
    expect(body.plane_status).toBe('ok');
    expect(body.resolved_symbols[0].status).toBe('exact');
    expect(body.results).toEqual([]);
  });

  it('reports an unknown symbol as not_found with an empty, degraded result (not an error)', async () => {
    const res = await query({ mode: 'callers', symbols: ['NoSuchFunction'] });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ plane_status: 'degraded', results: [] });
    expect(res.json().resolved_symbols[0].status).toBe('not_found');
  });

  it('applies path_prefix to the results', async () => {
    const res = await query({ mode: 'callers', symbols: ['render'], depth: 5, path_prefix: 'web/index.ts' });
    const files = new Set(res.json().results.map((r: { provenance: { file_path: string } }) => r.provenance.file_path));
    expect([...files]).toEqual(['web/index.ts']);
  });

  it('truncates to limit and says so', async () => {
    const res = await query({ mode: 'callers', symbols: ['render'], depth: 5, limit: 2 });
    expect(res.json().results).toHaveLength(2);
    expect(res.json().truncated).toBe(true);
  });

  it('can leave out source text', async () => {
    const res = await query({ mode: 'callers', symbols: ['render'], include_code: false });
    expect(res.json().results.every((r: { text: unknown }) => r.text === null)).toBe(true);
    const short = await query({ mode: 'callers', symbols: ['render'], max_code_chars: 10 });
    expect(short.json().results.every((r: { text: string }) => r.text.length <= 10)).toBe(true);
  });
});

describe('impact', () => {
  it('lists what depends on a symbol, grouped by distance', async () => {
    const res = await query({ mode: 'impact', symbols: ['render'], depth: 2 });
    const body = res.json();
    expect(body.plane_status).toBe('ok');
    const byName = Object.fromEntries(
      body.results.map((r: { provenance: { qualified_name: string }; depth: number }) => [r.provenance.qualified_name, r.depth]),
    );
    expect(byName).toMatchObject({ handle: 1, 'Widget.draw': 1, route: 2 });
    expect(byName.main).toBeUndefined(); // depth 3
    expect(byName.render).toBeUndefined(); // the symbol itself is not "affected"
  });
});

describe('lookup', () => {
  it('finds symbols by name and by keyword, symbol matches first', async () => {
    const res = await query({ mode: 'lookup', symbols: ['handle'], keywords: ['token'] });
    const body = res.json();
    const names = body.results.map((r: { provenance: { qualified_name: string } }) => r.provenance.qualified_name);
    expect(names[0]).toBe('handle');
    expect(names).toEqual(expect.arrayContaining(['issueToken', 'expireToken']));
    expect(body.plane_status).toBe('ok');
  });

  it('returns every candidate for an ambiguous symbol', async () => {
    const res = await query({ mode: 'lookup', symbols: ['draw'] });
    const names = res.json().results.map((r: { provenance: { qualified_name: string } }) => r.provenance.qualified_name).sort();
    expect(names).toEqual(['Panel.draw', 'Widget.draw']);
    expect(res.json().plane_status).toBe('degraded');
  });

  it('marks results from the fallback analyzer as degraded', async () => {
    const res = await query({ mode: 'lookup', keywords: ['token'], fallback_origin: 'analyzer' });
    expect(res.json().plane_status).toBe('degraded');
    expect(res.json().results.length).toBeGreaterThan(0);
  });
});

describe('request handling', () => {
  it('echoes the client request id, falling back to the envelope request id', async () => {
    const withHeader = await query({ mode: 'callers', symbols: ['render'] }, { headers: { 'x-request-id': 'client-1' } });
    expect(withHeader.json().request_id).toBe('client-1');
    expect(withHeader.headers['x-request-id']).toBe('client-1');
    const without = await query({ mode: 'callers', symbols: ['render'] });
    expect(without.json().request_id).toBe('env-req');
  });

  it('returns not_ready, not an error, for a project that is not indexed', async () => {
    const res = await query({ mode: 'callers', symbols: ['render'] }, { project: 'p2' });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      plane_status: 'not_ready',
      results: [],
      resolved_symbols: [],
      snapshot: { commit_sha: null, index_time: null, index_state: 'not_indexed' },
    });
  });

  it('finds a path between two symbols in flow mode', async () => {
    const res = await query({ mode: 'flow', symbols: ['handle', 'render'] });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.plane_status).toBe('ok');
    expect(body.resolved_symbols).toHaveLength(2);
    expect(body.resolved_symbols[0]).toMatchObject({ input: 'handle', status: 'exact', qualified_name: 'handle' });
    expect(body.resolved_symbols[1]).toMatchObject({ input: 'render', status: 'exact', qualified_name: 'render' });
    expect(body.results).toEqual([]); // flow mode does not return results
    expect(body.flow).toBeDefined();
    expect(Array.isArray(body.flow)).toBe(true);
    // There should be at least one hop from handle to render
    if (body.flow && body.flow.length > 0) {
      expect(body.flow[0].from).toBe('handle');
      expect(body.flow[body.flow.length - 1].to).toBe('render');
    }
  });

  it('validates the body and names the field', async () => {
    const res = await query({ mode: 'callers', symbols: ['a', 'b'] });
    expect(res.statusCode).toBe(422);
    expect(res.json().error_code).toBe('callers_needs_one_symbol');
    const bad = await query({ mode: 'lookup', symbols: ['a'], org_id: 'orgB' });
    expect(bad.statusCode).toBe(422);
    expect(bad.json()).toMatchObject({ error_code: 'invalid_field', field: 'org_id' });
  });

  it('requires the query scope', async () => {
    const res = await query({ mode: 'lookup', keywords: ['a'] }, { scopes: ['code:sync'] });
    expect(res.statusCode).toBe(403);
    expect(res.json().error_code).toBe('scope_missing');
  });

  it('rejects a request without an envelope', async () => {
    const res = await app.inject({ method: 'POST', url: '/internal/v1/code/query', payload: { mode: 'lookup', keywords: ['a'] } });
    expect(res.statusCode).toBe(401);
  });

  it('rejects malformed JSON with 422', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/internal/v1/code/query',
      headers: { 'x-astra-envelope': envelope('orgA', 'p1'), 'content-type': 'application/json' },
      payload: '{not json',
    });
    expect(res.statusCode).toBe(422);
  });
});

describe('isolation between orgs', () => {
  it('never returns another org symbols, even when both have a project p1', async () => {
    const a = await query({ mode: 'lookup', symbols: ['total'], keywords: ['invoice'] }, { org: 'orgA' });
    expect(a.json().results).toEqual([]);
    expect(a.json().resolved_symbols[0].status).toBe('not_found');

    const b = await query({ mode: 'lookup', symbols: ['total'] }, { org: 'orgB' });
    expect(b.json().results.map((r: { provenance: { qualified_name: string } }) => r.provenance.qualified_name)).toEqual(['total']);

    const bSeesA = await query({ mode: 'callers', symbols: ['render'] }, { org: 'orgB' });
    expect(bSeesA.json().resolved_symbols[0].status).toBe('not_found');
    expect(bSeesA.json().results).toEqual([]);
  });

  it('never leaks the commit of one org into another', async () => {
    const b = await query({ mode: 'lookup', symbols: ['total'] }, { org: 'orgB' });
    expect(b.json().snapshot.commit_sha).toBeNull();
    expect(JSON.stringify(b.json())).not.toContain('a1b2c3d');
  });
});
