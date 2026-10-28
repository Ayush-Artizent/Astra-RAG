import { createRequire } from 'node:module';
import path from 'node:path';
import type { JobPhase } from './types.js';
import { type RunResult, runProcess } from './process.js';

const require = createRequire(import.meta.url);

/**
 * The launcher script of the pinned CodeGraph package. It starts CodeGraph's own bundled Node, so the CLI does
 * not depend on the Node that runs the adapter. Running it needs the matching platform package to be installed;
 * if it is missing the launcher tries to download it, so deployments must install it.
 */
export function codegraphLauncher(): string {
  return path.join(path.dirname(require.resolve('@colbymchenry/codegraph/package.json')), 'npm-shim.js');
}

export interface CodegraphRun {
  cwd?: string;
  timeoutMs: number;
  signal?: AbortSignal;
  onLine?: (line: string) => void;
}

/** Runs a CodeGraph CLI command (`init`, `sync`, ...) as a child process, so a long run cannot block queries. */
export function runCodegraph(args: readonly string[], run: CodegraphRun): Promise<RunResult> {
  return runProcess(process.execPath, [codegraphLauncher(), ...args], {
    cwd: run.cwd,
    timeoutMs: run.timeoutMs,
    signal: run.signal,
    onLine: run.onLine,
    // Telemetry stays off even if the parent environment was changed.
    env: { ...process.env, CODEGRAPH_TELEMETRY: '0' },
  });
}

/** Coarse progress for each phase the CLI announces. Resolving and linking take most of the time on big repos. */
export const PHASE_PROGRESS: Record<JobPhase, number> = {
  clone: 0.05,
  scanning: 0.1,
  parsing: 0.2,
  resolving: 0.5,
  linking: 0.9,
  finalizing: 0.95,
};

/** Maps a line of CLI output such as `Resolving refs...` to the phase it announces. */
export function phaseOfLine(line: string): JobPhase | null {
  if (/scanning files/i.test(line)) return 'scanning';
  if (/parsing code/i.test(line)) return 'parsing';
  if (/resolving ref/i.test(line)) return 'resolving';
  if (/linking/i.test(line)) return 'linking';
  return null;
}
