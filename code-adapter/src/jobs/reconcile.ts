import { PHASE_PROGRESS } from './codegraph-cli.js';
import { type JobEnvironment, budget, measureAndStore, prepare } from './common.js';
import { collectGarbage, git, headSha, looseObjects, remoteHead } from './git.js';
import { checkProject } from './health.js';
import type { Executor, ExecutorDeps } from './types.js';
import { removeDir } from './workspace.js';

const DAY_MS = 86_400_000;
const short = (sha: string) => sha.slice(0, 7);

/**
 * Reconcile: bring one project back in line with reality. It runs as an ordinary job, so nothing else is running
 * on the project while it works. In order:
 *
 * 1. A pruned project is rebuilt (a query asked for it, since the schedule skips pruned projects).
 * 2. A project nobody has queried for `idleProjectDays` is pruned (off by default).
 * 3. A project whose folder or index is damaged is deleted and rebuilt.
 * 4. The remote branch head is compared with the commit the index reflects; if the index is behind (a missed
 *    webhook), a sync is queued. CodeGraph already handles force-pushes, so no history check is needed.
 * 5. `git gc` runs when loose git objects pile up, and disk use is measured.
 *
 * A rebuild is queued as an ordinary bootstrap job, so the one-bootstrap-at-a-time rule still holds.
 */
export function createReconcileExecutor(env: JobEnvironment, deps: ExecutorDeps): Executor {
  return async (ctx) => {
    const { project, signal } = ctx;
    const { orgId, projectId } = project;
    const prepared = prepare(env, project);
    const { dir, gitEnv, secrets } = prepared;
    const left = budget(env.config.syncTimeoutMs, 'Reconcile');
    const run = () => ({ env: gitEnv, timeoutMs: left(), signal, secrets });

    ctx.update({ phase: 'checking', progress: PHASE_PROGRESS.checking });

    // 1. Rebuild on demand.
    if (project.prunedAt !== null) {
      deps.enqueueBootstrap(orgId, projectId);
      return { detail: 'queued a rebuild, because a query needs the pruned project' };
    }

    // 2. Idle pruning.
    const days = env.config.idleProjectDays;
    if (days > 0) {
      const lastUsed = project.lastUsedAt ?? project.bootstrappedAt ?? project.createdAt;
      if (Date.now() - lastUsed > days * DAY_MS) {
        env.registry.evict(orgId, projectId);
        await removeDir(dir);
        deps.store.markPruned(orgId, projectId);
        return { detail: `pruned: not queried for more than ${days} days; it is rebuilt on the next query` };
      }
    }

    // 3. A damaged project is rebuilt.
    const health = await checkProject(dir);
    if (!health.ok) {
      env.registry.evict(orgId, projectId);
      await removeDir(dir);
      deps.enqueueBootstrap(orgId, projectId);
      return { detail: `queued a rebuild, because ${health.reason}` };
    }
    const stamp = health.stamp;

    // Files and index disagree (a sync that was cut off): move the files back to the commit the index reflects.
    const head = await headSha(dir, run());
    let notes = '';
    if (head !== stamp) {
      await git(['reset', '--hard', '--quiet', stamp], { ...run(), cwd: dir });
      notes += `; moved the files back to ${short(stamp)}, which the index reflects`;
    }

    // 4. Compare with the remote.
    const remote = await remoteHead(dir, project.branch, run());
    deps.store.noteRemoteHead(orgId, projectId, remote, stamp);
    let detail: string;
    if (remote === stamp) {
      detail = `up to date at ${short(stamp)}`;
    } else {
      const job = deps.enqueueSync(orgId, projectId, remote);
      detail = `behind: the remote is at ${short(remote)} and the index at ${short(stamp)}; queued sync ${job.id}`;
    }

    // 5. Housekeeping.
    ctx.update({ phase: 'maintenance', progress: PHASE_PROGRESS.maintenance });
    const loose = await looseObjects(dir, run());
    if (loose.looseKb >= env.config.gcLooseKb || loose.looseCount >= env.config.gcLooseObjects) {
      await collectGarbage(dir, run());
      const after = await looseObjects(dir, run());
      notes += `; ran git gc (loose objects ${loose.looseCount} (${loose.looseKb} KB) -> ${after.looseCount} (${after.looseKb} KB))`;
    }
    await measureAndStore(deps.store, orgId, projectId, dir);

    ctx.update({ phase: 'finalizing', progress: PHASE_PROGRESS.finalizing });
    return { detail: detail + notes };
  };
}
