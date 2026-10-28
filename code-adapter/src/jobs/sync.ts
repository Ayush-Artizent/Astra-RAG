import fs from 'node:fs';
import path from 'node:path';
import { isInitialized } from '../codegraph.js';
import { PHASE_PROGRESS, phaseOfLine, runCodegraph } from './codegraph-cli.js';
import { type JobEnvironment, budget, prepare, summariseIndex, verifyCheckout } from './common.js';
import { git } from './git.js';
import { scrubText } from './scrub.js';
import { readIndexedCommit } from './stamp.js';
import type { Executor, JobPhase } from './types.js';

/**
 * Sync: move the working tree to the requested commit, then let CodeGraph bring the index up to date.
 *
 * Steps: fetch the commit, `reset --hard` to it, check the checkout, `codegraph sync` as a child process, check
 * the index (complete, stamped with that commit). CodeGraph finds what changed on its own (a git diff from the
 * commit it last indexed, falling back to hashing every file), so nothing here compares files.
 *
 * Never runs `git clean`: it would delete the untracked `.codegraph` folder, which is the index.
 *
 * If indexing fails after the tree moved, the tree is moved back to the commit the index reflects, so that the
 * files and the index agree again.
 */
export function createSyncExecutor(env: JobEnvironment): Executor {
  return async (ctx) => {
    const { project, signal, job } = ctx;
    const commit = job.commitSha;
    if (!commit) throw new Error('A sync job needs a commit');
    const prepared = prepare(env, project);
    const { dir, gitEnv, secrets } = prepared;
    const left = budget(env.config.syncTimeoutMs, 'Sync');
    const gitRun = () => ({ cwd: dir, env: gitEnv, timeoutMs: left(), signal, secrets });

    if (!fs.existsSync(path.join(dir, '.git')) || !isInitialized(dir)) {
      throw new Error('The project has no checkout and index on disk, so there is nothing to sync; it must be bootstrapped again');
    }

    // The commit the index reflects now. Also where the tree goes back to if this sync fails.
    const before = readIndexedCommit(dir);

    // Already there (a repeated push event): no fetch and no indexing.
    if (before === commit) {
      ctx.update({ phase: 'finalizing', progress: PHASE_PROGRESS.finalizing });
      return summariseIndex(dir, commit);
    }

    let moved = false;
    try {
      ctx.update({ phase: 'clone', progress: PHASE_PROGRESS.clone });
      await fetchCommit(commit, project.branch, gitRun);
      await git(['reset', '--hard', '--quiet', commit], gitRun());
      moved = true;
      const head = await verifyCheckout(prepared, left(), signal);
      if (head !== commit) throw new Error(`The checkout is at ${head}, not the requested commit ${commit}`);

      let current: JobPhase = 'scanning';
      ctx.update({ phase: current, progress: PHASE_PROGRESS[current] });
      const run = await (env.runCodegraph ?? runCodegraph)(['sync', dir], {
        timeoutMs: left(),
        signal,
        onLine: (line) => {
          const phase = phaseOfLine(line);
          if (phase && phase !== current) {
            current = phase;
            ctx.update({ phase, progress: PHASE_PROGRESS[phase] });
          }
        },
      });
      if (run.aborted) throw new Error('Cancelled');
      if (run.timedOut) throw new Error(`Sync timed out after ${Math.round(env.config.syncTimeoutMs / 1000)}s while indexing`);
      if (run.code !== 0) {
        throw new Error(`codegraph sync failed (exit ${run.code}): ${scrubText(run.stderr.trim() || run.stdout.trim(), secrets)}`);
      }

      ctx.update({ phase: 'finalizing', progress: PHASE_PROGRESS.finalizing });
      return await summariseIndex(dir, commit);
    } catch (e) {
      const problem = e instanceof Error ? e.message : String(e);
      const note = moved && before ? await moveBack(before, dir, gitEnv, secrets) : null;
      throw new Error(note ? `${problem} (${note})` : problem);
    }
  };
}

/**
 * Gets the commit into the repo. Tries it by id first, which works on GitHub and GitLab for any reachable commit.
 * If the server refuses that, the commit is accepted only if it is the current tip of the tracked branch.
 */
async function fetchCommit(
  commit: string,
  branch: string | null,
  run: () => { cwd: string; env: NodeJS.ProcessEnv; timeoutMs: number; signal: AbortSignal; secrets: string[] },
): Promise<void> {
  const common = ['fetch', '--depth', '1', '--no-tags', '--no-recurse-submodules', 'origin'];
  try {
    await git([...common, commit], run());
    return;
  } catch (byId) {
    if ((byId as Error).message === 'Cancelled') throw byId;
    const refspec = branch ?? 'HEAD';
    try {
      await git([...common, refspec], run());
      const tip = await git(['rev-parse', 'FETCH_HEAD'], run());
      if (tip === commit) return;
    } catch {
      // fall through to the original, more useful error
    }
    throw byId;
  }
}

/** Best effort: put the tree back on the commit the index still reflects. Returns a note describing the outcome. */
async function moveBack(
  commit: string,
  dir: string,
  gitEnv: NodeJS.ProcessEnv,
  secrets: string[],
): Promise<string> {
  try {
    await git(['reset', '--hard', '--quiet', commit], { cwd: dir, env: gitEnv, timeoutMs: 120_000, secrets });
    return `the checkout was moved back to ${commit.slice(0, 7)}, which the index still reflects`;
  } catch (e) {
    const why = e instanceof Error ? e.message : String(e);
    return `the checkout could not be moved back to ${commit.slice(0, 7)}, so files and index may disagree until the next sync: ${why}`;
  }
}
