import './env.js';
import { createRequire } from 'node:module';
import Fastify, { type FastifyError, type FastifyInstance, type FastifyRequest } from 'fastify';
import type { Config } from './config.js';
import { type Envelope, requireScope, verifyEnvelope } from './envelope.js';
import { ProblemError } from './errors.js';
import { createExecutors, createRecoveryFor } from './jobs/executors.js';
import { createJobSystem, type JobSystem } from './jobs/index.js';
import { registerJobRoutes } from './jobs/routes.js';
import { readIndexedCommit } from './jobs/stamp.js';
import type { Executor, JobType } from './jobs/types.js';
import type { GraphApi } from './modes.js';
import { projectDir } from './paths.js';
import { ProjectRegistry } from './projects.js';
import { type AmbiguousPolicy, runCodeQuery } from './query.js';
import { snapshotOf, type CodeQueryResponse } from './shape.js';
import { buildStatus, type CodeStatus } from './status.js';
import { validateCodeQuery } from './validate.js';
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

/** A sync or bootstrap is running for the project, so its files and index may briefly disagree. */
function isSyncing(jobs: JobSystem, env: Envelope): boolean {
  return jobs.store
    .activeForProject(env.org_id, env.project_id)
    .some((j) => j.state === 'running' && (j.type === 'sync' || j.type === 'bootstrap'));
}

function requestIdOf(req: FastifyRequest): string | undefined {
  const hdr = req.headers['x-request-id'];
  return (Array.isArray(hdr) ? hdr[0] : hdr)?.slice(0, 64);
}

export interface ServerDeps {
  registry?: ProjectRegistry;
  /** Replaces the whole job system. For tests that need to control it. */
  jobs?: JobSystem;
  /** What runs each job type. Defaults to the real executors (git clone and the CodeGraph CLI). */
  executors?: Partial<Record<JobType, Executor>>;
  ambiguousPolicy?: AmbiguousPolicy;
  /** The commit a project's index reflects. Defaults to reading CodeGraph's own stamp from the index. */
  commitSha?: (orgId: string, projectId: string) => string | null;
}

export function buildServer(config: Config, deps: ServerDeps = {}): FastifyInstance {
  const app = Fastify({ logger: false, bodyLimit: 64 * 1024 });
  const probe = walProbe();
  const registry = deps.registry ?? new ProjectRegistry({ dataDir: config.dataDir });
  // The commit an index reflects is read from the index itself (work plan, decision 6).
  const commitSha = deps.commitSha ?? ((org, project) => readIndexedCommit(projectDir(config.dataDir, org, project)));
  const jobs =
    deps.jobs ??
    createJobSystem(config, {
      executors: deps.executors ?? createExecutors(config, registry),
      recover: createRecoveryFor(config, registry),
    });
  app.addHook('onReady', async () => jobs.queue.start());
  app.addHook('onClose', async () => {
    await jobs.close();
    registry.closeAll();
  });

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

  app.post('/internal/v1/code/query', async (req): Promise<CodeQueryResponse> => {
    const env = req.envelope as Envelope;
    requireScope(env, 'query');
    const q = validateCodeQuery(req.body);
    if (q.mode === 'flow') {
      // TODO(phase 2): flow mode (findPath over `calls` edges).
      throw new ProblemError(501, 'not_implemented', 'Not implemented', 'flow mode is not available yet');
    }

    const requestId = requestIdOf(req) ?? env.request_id;
    const lease = await registry.acquire(env.org_id, env.project_id);
    try {
      const p = lease.project;
      const snapshot = snapshotOf(p, commitSha(env.org_id, env.project_id), isSyncing(jobs, env));
      if (!p.ready) {
        return { request_id: requestId, plane_status: 'not_ready', snapshot, resolved_symbols: [], results: [], truncated: false };
      }
      return await runCodeQuery(p.cg as unknown as GraphApi, q, {
        requestId,
        snapshot,
        ambiguousPolicy: deps.ambiguousPolicy,
      });
    } finally {
      lease.release();
    }
  });

  registerJobRoutes(app, jobs.service);

  app.get('/internal/v1/code/status', async (req): Promise<CodeStatus> => {
    const env = req.envelope as Envelope;
    requireScope(env, 'query');
    const lease = await registry.acquire(env.org_id, env.project_id);
    try {
      const active = jobs.store.activeForProject(env.org_id, env.project_id);
      const running = active.find((j) => j.state === 'running');
      const shown = running ?? active[0];
      return buildStatus(
        lease.project,
        commitSha(env.org_id, env.project_id),
        shown ? { id: shown.id, running: running !== undefined } : null,
        isSyncing(jobs, env),
      );
    } finally {
      lease.release();
    }
  });

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
