import fs from 'node:fs';
import { type JobEnvironment, prepare } from './common.js';
import { git, headSha } from './git.js';
import { readIndexedCommit } from './stamp.js';
import type { JobRow, ProjectBinding } from './types.js';
import { removeDir } from './workspace.js';

/**
 * Undoes what a job left behind when the adapter was stopped or crashed while it ran.
 *
 * - A bootstrap that was cut off owns its folder (it refuses to start in a folder that has content), so the
 *   half-made clone is deleted. Without this the project would stay `indexing` forever, and the repo record
 *   would make every retry a conflict.
 * - A sync that was cut off may have moved the files to the new commit without the index following. The files
 *   are moved back to the commit the index reflects, so the two agree until the next sync.
 */
export function createRecovery(env: JobEnvironment, bindingOf: (job: JobRow) => ProjectBinding | undefined) {
  return async (job: JobRow): Promise<void> => {
    const project = bindingOf(job);
    if (!project) return;
    const { dir, gitEnv, secrets } = prepare(env, project);

    if (job.type === 'bootstrap') {
      env.registry.evict(job.orgId, job.projectId);
      await removeDir(dir);
      return;
    }

    if (job.type === 'sync') {
      if (!fs.existsSync(dir)) return;
      const indexed = readIndexedCommit(dir);
      if (!indexed) return;
      const run = { env: gitEnv, timeoutMs: 120_000, secrets };
      const head = await headSha(dir, run);
      if (head !== indexed) await git(['reset', '--hard', '--quiet', indexed], { ...run, cwd: dir });
    }
  };
}
