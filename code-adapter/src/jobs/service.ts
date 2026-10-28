import { type Envelope, requireScope } from '../envelope.js';
import { ProblemError } from '../errors.js';
import type { JobQueue } from './queue.js';
import type { JobStore } from './store.js';
import type { JobRequest, JobRow } from './types.js';
import { type RepoUrlPolicy, requestHash, validateIdempotencyKey, validateJobRequest } from './validate.js';

const conflict = (detail: string) => new ProblemError(409, 'job_conflict', 'Conflict', detail);

export interface JobServiceDeps {
  store: JobStore;
  queue: JobQueue;
  policy: RepoUrlPolicy;
  /** Whether something already exists on disk for the project, for example an index put there by hand. */
  existsOnDisk: (orgId: string, projectId: string) => boolean;
}

const SCOPE: Record<JobRequest['type'], string> = {
  bootstrap: 'project:admin',
  sync: 'code:sync',
  reconcile: 'code:sync',
};

/** The rules for accepting a job. The routes only translate HTTP to and from this. */
export class JobService {
  constructor(private readonly deps: JobServiceDeps) {}

  /** Validates, authorises and queues a job, or returns the existing one for a repeated Idempotency-Key. */
  submit(env: Envelope, body: unknown, idempotencyKeyHeader: string | undefined): JobRow {
    const { store, queue, policy } = this.deps;
    const req = validateJobRequest(body, policy);
    const key = validateIdempotencyKey(idempotencyKeyHeader);
    requireScope(env, SCOPE[req.type]);
    if (req.type === 'reconcile') {
      // TODO(phase 2, L5): reconcile compares the index commit with the remote branch head.
      throw new ProblemError(501, 'not_implemented', 'Not implemented', 'reconcile jobs are not available yet');
    }

    const hash = requestHash(req);
    if (key !== undefined) {
      const earlier = store.findByIdempotencyKey(env.org_id, env.project_id, key);
      if (earlier) {
        if (earlier.requestHash === hash) return earlier;
        throw conflict('This Idempotency-Key was already used for a different request');
      }
    }

    if (req.type === 'bootstrap') {
      if (this.deps.existsOnDisk(env.org_id, env.project_id)) {
        throw conflict('The project already has data on disk; bootstrap does not rebuild an existing project');
      }
      const added = store.addProject({
        orgId: env.org_id,
        projectId: env.project_id,
        repoUrl: req.repoUrl,
        branch: req.branch,
        credentialsRef: req.credentialsRef,
      });
      if (!added) throw conflict('The project is already bootstrapped or is being bootstrapped');
      const job = store.create({ orgId: env.org_id, projectId: env.project_id, type: 'bootstrap', idempotencyKey: key, requestHash: hash });
      queue.kick();
      return store.get(job.id) as JobRow;
    }

    const project = store.getProject(env.org_id, env.project_id);
    if (!project || project.bootstrappedAt === null) {
      throw conflict('The project has not been bootstrapped yet');
    }
    const job = store.create({
      orgId: env.org_id,
      projectId: env.project_id,
      type: 'sync',
      commitSha: req.commitSha,
      idempotencyKey: key,
      requestHash: hash,
    });
    // Only the newest queued sync matters: a sync moves the tree to its commit, so older ones add nothing.
    store.supersedeQueuedSyncs(env.org_id, env.project_id, job.id);
    queue.kick();
    return store.get(job.id) as JobRow;
  }

  /** A job of this org and project. A job from anywhere else is reported as not found. */
  get(env: Envelope, id: string): JobRow {
    if (!['query', 'code:sync', 'project:admin'].some((s) => env.scopes.includes(s))) {
      throw new ProblemError(403, 'scope_missing', 'Forbidden', 'Missing scope query, code:sync or project:admin');
    }
    const job = this.deps.store.getScoped(id, env.org_id, env.project_id);
    if (!job) throw new ProblemError(404, 'project_unknown', 'Not found', 'No such job');
    return job;
  }
}
