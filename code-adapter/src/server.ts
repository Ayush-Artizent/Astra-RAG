import './env.js';
import { createRequire } from 'node:module';
import Fastify, { type FastifyError, type FastifyInstance, type FastifyRequest } from 'fastify';
import type { Config } from './config.js';
import { type Envelope, verifyEnvelope } from './envelope.js';
import { ProblemError } from './errors.js';
import { walProbe } from './wal-probe.js';

declare module 'fastify' {
  interface FastifyRequest {
    envelope?: Envelope;
  }
}

const require = createRequire(import.meta.url);
const PROBLEM_JSON = 'application/problem+json';

function codegraphVersion(): string {
  try {
    return (require('@colbymchenry/codegraph/package.json') as { version: string }).version;
  } catch {
    return 'unknown';
  }
}

function requestIdOf(req: FastifyRequest): string | undefined {
  const hdr = req.headers['x-request-id'];
  return (Array.isArray(hdr) ? hdr[0] : hdr)?.slice(0, 64);
}

export function buildServer(config: Config): FastifyInstance {
  const app = Fastify({ logger: false, bodyLimit: 64 * 1024 });
  const probe = walProbe();

  app.addHook('onRequest', async (req, reply) => {
    const id = requestIdOf(req);
    if (id) reply.header('x-request-id', id);
  });

  // Everything under /internal/v1/ except health needs a valid envelope.
  app.addHook('preHandler', async (req) => {
    const url = req.url.split('?')[0] ?? '';
    if (!url.startsWith('/internal/v1/') || url === '/internal/v1/health') return;
    const header = req.headers['x-astra-envelope'];
    req.envelope = verifyEnvelope(Array.isArray(header) ? header[0] : header, {
      key: config.envelopeKey,
      maxLifetimeSeconds: config.maxEnvelopeLifetimeSeconds,
      clockSkewSeconds: config.clockSkewSeconds,
    });
  });

  app.get('/internal/v1/health', async () => ({
    status: probe === 'ok' ? 'ok' : 'degraded',
    codegraph_version: codegraphVersion(),
    node_version: process.version,
    wal_probe: probe,
    active_jobs: 0,
  }));

  app.setNotFoundHandler((req, reply) => {
    reply.code(404).type(PROBLEM_JSON).send({
      type: 'about:blank',
      title: 'Not found',
      status: 404,
      detail: 'Unknown route',
      request_id: requestIdOf(req),
    });
  });

  app.setErrorHandler((err: FastifyError | ProblemError, req, reply) => {
    const requestId = requestIdOf(req);
    if (err instanceof ProblemError) {
      return reply.code(err.status).type(PROBLEM_JSON).send({
        type: 'about:blank',
        title: err.title,
        status: err.status,
        detail: err.message,
        error_code: err.errorCode,
        ...(err.field ? { field: err.field } : {}),
        request_id: requestId,
      });
    }
    const status = (err as FastifyError).statusCode ?? 500;
    if (status >= 400 && status < 500) {
      const mapped = status === 400 ? 422 : status;
      return reply.code(mapped).type(PROBLEM_JSON).send({
        type: 'about:blank',
        title: 'Invalid request',
        status: mapped,
        detail: err.message,
        error_code: 'invalid_field',
        request_id: requestId,
      });
    }
    return reply.code(500).type(PROBLEM_JSON).send({
      type: 'about:blank',
      title: 'Internal error',
      status: 500,
      request_id: requestId,
    });
  });

  return app;
}
