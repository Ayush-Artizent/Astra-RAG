import type { Config } from '../config.js';
import type { ProjectRegistry } from '../projects.js';
import { createBootstrapExecutor } from './bootstrap.js';
import { ensureEmptyGitConfig, type JobEnvironment } from './common.js';
import { createRecovery } from './recovery.js';
import { createSyncExecutor } from './sync.js';
import type { Executor, JobRow, JobType, ProjectBinding } from './types.js';

/** Startup cleanup for jobs a restart cut off, using the same environment as the executors. */
export function createRecoveryFor(
  config: Config,
  registry: ProjectRegistry,
): (job: JobRow, project: ProjectBinding | undefined) => Promise<void> {
  const env: JobEnvironment = { config, registry, emptyGitConfig: ensureEmptyGitConfig(config.dataDir) };
  return (job, project) => createRecovery(env, () => project)(job);
}

/**
 * The real executors. Each job type is a function the queue runs; the queue knows nothing about git or CodeGraph.
 * `overrides` lets tests replace the CodeGraph CLI.
 * TODO(phase 2, L5): the `reconcile` executor.
 */
export function createExecutors(
  config: Config,
  registry: ProjectRegistry,
  overrides: Pick<JobEnvironment, 'runCodegraph'> = {},
): Partial<Record<JobType, Executor>> {
  const env: JobEnvironment = { config, registry, emptyGitConfig: ensureEmptyGitConfig(config.dataDir), ...overrides };
  return {
    bootstrap: createBootstrapExecutor(env),
    sync: createSyncExecutor(env),
  };
}
