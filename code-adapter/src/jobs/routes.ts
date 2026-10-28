import type { FastifyInstance } from 'fastify';
import type { Envelope } from '../envelope.js';
import type { JobService } from './service.js';
import type { JobPhase, JobRow, JobState, JobType } from './types.js';

export interface JobAccepted {
  job_id: string;
  status_url: string;
  state: JobState;
}

export interface JobOut {
  job_id: string;
  type: JobType;
  state: JobState;
  commit_sha: string | null;
  coalesced_into: string | null;
  created_at: string;
  /** What a finished job did, in a sentence. */
  detail: string | null;
  phase: JobPhase | null;
  progress: number | null;
  started_at: string | null;
  finished_at: string | null;
  counts?: { files: number; symbols: number; edges: number };
  error: string | null;
}

const iso = (ms: number | null): string | null => (ms === null ? null : new Date(ms).toISOString());
const statusUrl = (id: string) => `/internal/v1/code/jobs/${id}`;

export function jobOut(j: JobRow): JobOut {
  const out: JobOut = {
    job_id: j.id,
    type: j.type,
    state: j.state,
    commit_sha: j.commitSha,
    coalesced_into: j.coalescedInto,
    created_at: iso(j.createdAt) as string,
    detail: j.detail,
    phase: j.phase,
    progress: j.progress,
    started_at: iso(j.startedAt),
    finished_at: iso(j.finishedAt),
    error: j.error,
  };
  if (j.files !== null || j.symbols !== null || j.edges !== null) {
    out.counts = { files: j.files ?? 0, symbols: j.symbols ?? 0, edges: j.edges ?? 0 };
  }
  return out;
}

export function registerJobRoutes(app: FastifyInstance, service: JobService): void {
  app.post('/internal/v1/code/jobs', async (req, reply): Promise<JobAccepted> => {
    const header = req.headers['idempotency-key'];
    const job = service.submit(req.envelope as Envelope, req.body, Array.isArray(header) ? header[0] : header);
    reply.code(202);
    return { job_id: job.id, status_url: statusUrl(job.id), state: job.state };
  });

  app.get('/internal/v1/code/jobs/:job_id', async (req): Promise<JobOut> => {
    const { job_id } = req.params as { job_id: string };
    return jobOut(service.get(req.envelope as Envelope, job_id));
  });
}
