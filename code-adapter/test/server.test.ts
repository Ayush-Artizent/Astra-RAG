import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { FastifyInstance } from 'fastify';
import type { Config } from '../src/config.js';
import { signEnvelope } from '../src/envelope.js';
import { buildServer } from '../src/server.js';

const config: Config = {
  port: 0,
  host: '127.0.0.1',
  dataDir: path.resolve('test-data-unused'),
  envelopeKey: 'test-key-0123456789abcdef',
  maxEnvelopeLifetimeSeconds: 300,
  clockSkewSeconds: 30,
};

let app: FastifyInstance;
beforeAll(async () => {
  app = buildServer(config);
  await app.ready();
});
afterAll(async () => {
  await app.close();
});

const now = () => Math.floor(Date.now() / 1000);
const envelopeHeader = () =>
  signEnvelope(
    { org_id: 'orgA', project_id: 'p1', scopes: ['query'], request_id: 'r', iat: now(), exp: now() + 60 },
    config.envelopeKey,
  );

describe('server', () => {
  it('serves health without an envelope and reports the WAL probe', async () => {
    const res = await app.inject({ method: 'GET', url: '/internal/v1/health' });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.wal_probe).toBe('ok');
    expect(body.status).toBe('ok');
    expect(body.codegraph_version).toBe('1.6.2');
    expect(body.node_version).toBe(process.version);
  });

  it('turns CodeGraph telemetry off for the process', () => {
    expect(process.env.CODEGRAPH_TELEMETRY).toBe('0');
  });

  it('returns 401 problem+json when the envelope is missing', async () => {
    const res = await app.inject({ method: 'GET', url: '/internal/v1/code/status' });
    expect(res.statusCode).toBe(401);
    expect(res.headers['content-type']).toContain('application/problem+json');
    expect(res.json().error_code).toBe('envelope_invalid');
  });

  it('returns 401 for a bad signature', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/internal/v1/code/status',
      headers: { 'x-astra-envelope': `${envelopeHeader()}x` },
    });
    expect(res.statusCode).toBe(401);
  });

  it('returns 404 problem+json for an unknown route with a valid envelope', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/internal/v1/nope',
      headers: { 'x-astra-envelope': envelopeHeader() },
    });
    expect(res.statusCode).toBe(404);
    expect(res.headers['content-type']).toContain('application/problem+json');
  });

  it('echoes X-Request-Id', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/internal/v1/health',
      headers: { 'x-request-id': 'abc-123' },
    });
    expect(res.headers['x-request-id']).toBe('abc-123');
  });
});
