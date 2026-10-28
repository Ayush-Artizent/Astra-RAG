import fs from 'node:fs';
import path from 'node:path';
import type { Config } from '../config.js';
import { projectDir } from '../paths.js';
import { measureAndStore } from './common.js';
import { Maintenance } from './maintenance.js';
import { JobQueue } from './queue.js';
import { JobService } from './service.js';
import { JobStore } from './store.js';
import type { Executor, ExecutorDeps, JobRow, JobType, ProjectBinding } from './types.js';

export interface JobSystem {
  store: JobStore;
  queue: JobQueue;
  service: JobService;
  maintenance: Maintenance;
  close(): Promise<void>;
}

type Executors = Partial<Record<JobType, Executor>>;

export interface JobSystemOptions {
  /**
   * What runs each job type. Either the executors themselves, or a function that builds them once the store and the
   * service exist (the real executors need both, to queue follow-up jobs).
   */
  executors: Executors | ((deps: ExecutorDeps) => Executors);
  /** Cleans up after a job a restart cut off. See `createRecovery`. Receives the job and its project's repo binding. */
  recover?: (job: JobRow, project: ProjectBinding | undefined) => Promise<void>;
  /** Where the job file lives. Defaults to `<dataDir>/.adapter/jobs.db`. `.adapter` cannot clash with an org id. */
  storeFile?: string;
}

/** Wires the store, the queue and the service together, and keeps a project's repo binding in step with its jobs. */
export function createJobSystem(config: Config, opts: JobSystemOptions): JobSystem {
  const store = new JobStore(opts.storeFile ?? path.join(config.dataDir, '.adapter', 'jobs.db'));
  // The queue reads this object when a job starts, so it can be filled in after the service exists.
  const executors: Executors = typeof opts.executors === 'function' ? {} : opts.executors;

  const queue = new JobQueue({
    store,
    executors,
    recover: opts.recover ? (job) => opts.recover!(job, store.getProject(job.orgId, job.projectId)) : undefined,
    maxConcurrent: config.maxConcurrentJobs,
    onSettled: (job, outcome) => {
      const dir = projectDir(config.dataDir, job.orgId, job.projectId);
      if (job.type === 'bootstrap') {
        if (outcome === 'done') {
          store.markBootstrapped(job.orgId, job.projectId);
          void measureAndStore(store, job.orgId, job.projectId, dir);
        } else if (store.getProject(job.orgId, job.projectId)?.bootstrappedAt === null) {
          // A first bootstrap that failed leaves no binding behind, so the project can be bootstrapped again.
          // A rebuild that failed keeps it: the schedule retries.
          store.deleteProject(job.orgId, job.projectId);
        }
      } else if (job.type === 'sync' && outcome === 'done' && job.commitSha) {
        store.markCaughtUp(job.orgId, job.projectId, job.commitSha);
        void measureAndStore(store, job.orgId, job.projectId, dir);
      }
    },
  });

  const service = new JobService({
    store,
    queue,
    policy: { allowedRepoHosts: config.allowedRepoHosts, allowFileRepos: config.allowFileRepos },
    existsOnDisk: (org, project) => fs.existsSync(projectDir(config.dataDir, org, project)),
  });

  if (typeof opts.executors === 'function') {
    Object.assign(
      executors,
      opts.executors({
        store,
        enqueueSync: (org, project, sha) => service.enqueueSync(org, project, sha),
        enqueueBootstrap: (org, project) => service.enqueueBootstrap(org, project),
      }),
    );
  }

  const maintenance = new Maintenance({ store, service, intervalMs: config.reconcileIntervalMs });

  return {
    store,
    queue,
    service,
    maintenance,
    close: async () => {
      maintenance.stop();
      await queue.stop();
      store.close();
    },
  };
}
