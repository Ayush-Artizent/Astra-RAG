import fs from 'node:fs';
import path from 'node:path';
import { type JobEnvironment, budget, prepare, summariseIndex, verifyCheckout } from './common.js';
import { PHASE_PROGRESS, phaseOfLine, runCodegraph } from './codegraph-cli.js';
import { cloneShallow } from './git.js';
import { scrubText } from './scrub.js';
import type { Executor, JobPhase } from './types.js';
import { isNonEmptyDir, removeDir } from './workspace.js';

/**
 * Bootstrap: a shallow clone of the repo into `<data>/<org>/<project>/`, then the first index.
 *
 * Steps: clone, check the checkout (own git root, no symlinks), `codegraph init` as a child process, check the
 * index (complete, stamped with the checked-out commit). Any failure deletes the half-built folder, so the
 * project is never left looking indexed or stuck in `indexing`, and the bootstrap can be retried.
 */
export function createBootstrapExecutor(env: JobEnvironment): Executor {
  return async (ctx) => {
    const { project, signal } = ctx;
    const prepared = prepare(env, project);
    const { dir, gitEnv, secrets } = prepared;
    const left = budget(env.config.bootstrapTimeoutMs, 'Bootstrap');

    // Never clear or reuse a folder somebody else filled: nothing below runs, and nothing is deleted.
    if (isNonEmptyDir(dir)) throw new Error('The project folder already has content, so it was left untouched');

    try {
      ctx.update({ phase: 'clone', progress: PHASE_PROGRESS.clone });
      fs.mkdirSync(path.dirname(dir), { recursive: true });
      await cloneShallow({
        url: project.repoUrl,
        dir,
        branch: project.branch,
        env: gitEnv,
        timeoutMs: left(),
        signal,
        secrets,
      });

      const commit = await verifyCheckout(prepared, left(), signal);

      let current: JobPhase = 'scanning';
      ctx.update({ phase: current, progress: PHASE_PROGRESS[current] });
      const index = await (env.runCodegraph ?? runCodegraph)(['init', dir], {
        timeoutMs: left(),
        signal,
        onLine: (line) => {
          const phase = phaseOfLine(line);
          // Report a phase once, when it starts. The CLI announces `scanning` again right away.
          if (phase && phase !== current) {
            current = phase;
            ctx.update({ phase, progress: PHASE_PROGRESS[phase] });
          }
        },
      });
      if (index.aborted) throw new Error('Cancelled');
      if (index.timedOut) throw new Error(`Bootstrap timed out after ${Math.round(env.config.bootstrapTimeoutMs / 1000)}s while indexing`);
      if (index.code !== 0) {
        throw new Error(`codegraph init failed (exit ${index.code}): ${scrubText(index.stderr.trim() || index.stdout.trim(), secrets)}`);
      }

      ctx.update({ phase: 'finalizing', progress: PHASE_PROGRESS.finalizing });
      return await summariseIndex(dir, commit);
    } catch (e) {
      const problem = e instanceof Error ? e.message : String(e);
      const cleanup = await cleanUp(env, project.orgId, project.projectId, dir);
      throw new Error(cleanup ? `${problem} (${cleanup})` : problem);
    }
  };
}

/** Closes any handle on the folder and deletes it. Returns a note only if the folder could not be removed. */
async function cleanUp(env: JobEnvironment, orgId: string, projectId: string, dir: string): Promise<string | null> {
  try {
    env.registry.evict(orgId, projectId);
    await removeDir(dir);
    return null;
  } catch (e) {
    const why = e instanceof Error ? e.message : String(e);
    return `cleanup failed, so ${dir} must be removed by hand: ${why}`;
  }
}
