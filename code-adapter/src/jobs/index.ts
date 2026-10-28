import fs from 'node:fs';
import path from 'node:path';
import type { Config } from '../config.js';
import { projectDir } from '../paths.js';
import { JobQueue } from './queue.js';
import { JobService } from './service.js';
import { JobStore } from './store.js';
import type { Executor, JobRow, JobType, ProjectBinding } from './types.js';

export interface JobSystem {
  store: JobStore;
  queue: JobQueue;
  service: JobService;
  close(): Promise<void>;
}

export interface JobSystemOptions {
  executors: Partial<Record<JobType, Executor>>;
  /** Cleans up after a job a restart cut off. See `createRecovery`. Receives the job and its project's repo binding. */
  recover?: (job: JobRow, project: ProjectBinding | undefined) => Promise<void>;
  /** Where the job file lives. Defaults to `<dataDir>/.adapter/jobs.db`. `.adapter` cannot clash with an org id. */
  storeFile?: string;
}

/** Wires the store, the queue and the service together, and keeps a project's repo binding in step with its bootstrap. */
export function createJobSystem(config: Config, opts: JobSystemOptions): JobSystem {
  const store = new JobStore(opts.storeFile ?? path.join(config.dataDir, '.adapter', 'jobs.db'));
  const queue = new JobQueue({
    store,
    executors: opts.executors,
    recover: opts.recover ? (job) => opts.recover!(job, store.getProject(job.orgId, job.projectId)) : undefined,
    maxConcurrent: config.maxConcurrentJobs,
    onSettled: (job, outcome) => {
      if (job.type !== 'bootstrap') return;
      // A failed bootstrap leaves no binding behind, so the same project can be bootstrapped again.
      if (outcome === 'done') store.markBootstrapped(job.orgId, job.projectId);
      else store.deleteProject(job.orgId, job.projectId);
    },
  });
  const service = new JobService({
    store,
    queue,
    policy: { allowedRepoHosts: config.allowedRepoHosts, allowFileRepos: config.allowFileRepos },
    existsOnDisk: (org, project) => fs.existsSync(projectDir(config.dataDir, org, project)),
  });
  return {
    store,
    queue,
    service,
    close: async () => {
      await queue.stop();
      store.close();
    },
  };
}
