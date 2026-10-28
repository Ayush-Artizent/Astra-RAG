import { spawn } from 'node:child_process';

export interface RunOptions {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  /** The whole process tree is killed when this much time has passed. */
  timeoutMs: number;
  /** Aborting kills the whole process tree. */
  signal?: AbortSignal;
  /** Called with each complete line of stdout or stderr as it arrives. */
  onLine?: (line: string) => void;
}

export interface RunResult {
  /** Exit code, or null when the process was killed. */
  code: number | null;
  /** The start of stdout (capped), for commands whose output is parsed. */
  stdout: string;
  /** The end of stderr (capped), for error messages. */
  stderr: string;
  timedOut: boolean;
  aborted: boolean;
}

const STDOUT_CAP = 4 * 1024 * 1024;
const STDERR_TAIL = 16 * 1024;

/**
 * Kills a process and everything it started. Git starts helper processes and the CodeGraph launcher starts its
 * own Node, so killing only the direct child would leave them running.
 */
export function killTree(pid: number | undefined): void {
  if (pid === undefined) return;
  if (process.platform === 'win32') {
    try {
      spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true }).on('error', () => {});
    } catch {
      // nothing more can be done
    }
    return;
  }
  try {
    process.kill(-pid, 'SIGKILL'); // the child leads its own process group (see `detached` below)
  } catch {
    try {
      process.kill(pid, 'SIGKILL');
    } catch {
      // already gone
    }
  }
}

/**
 * Runs a command without a shell and without stdin. Resolves when the process has exited, including when it
 * was killed for taking too long or because the signal fired. Rejects only if the command could not be started.
 */
export function runProcess(command: string, args: readonly string[], opts: RunOptions): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    if (opts.signal?.aborted) {
      resolve({ code: null, stdout: '', stderr: '', timedOut: false, aborted: true });
      return;
    }

    const child = spawn(command, args, {
      cwd: opts.cwd,
      env: opts.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      detached: process.platform !== 'win32',
    });

    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let aborted = false;
    let settled = false;
    const partial = { out: '', err: '' };

    const lines = (key: 'out' | 'err', text: string) => {
      if (!opts.onLine) return;
      const parts = (partial[key] + text).split(/\r\n|\n|\r/);
      partial[key] = parts.pop() ?? '';
      for (const line of parts) if (line.length > 0) opts.onLine(line);
    };

    child.stdout.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8');
      if (stdout.length < STDOUT_CAP) stdout += text;
      lines('out', text);
    });
    child.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8');
      stderr = (stderr + text).slice(-STDERR_TAIL);
      lines('err', text);
    });

    const timer = setTimeout(() => {
      timedOut = true;
      killTree(child.pid);
    }, opts.timeoutMs);
    const onAbort = () => {
      aborted = true;
      killTree(child.pid);
    };
    opts.signal?.addEventListener('abort', onAbort, { once: true });

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      opts.signal?.removeEventListener('abort', onAbort);
      fn();
    };

    child.on('error', (err) => finish(() => reject(err)));
    child.on('close', (code) =>
      finish(() => {
        if (opts.onLine) {
          for (const rest of [partial.out, partial.err]) if (rest.length > 0) opts.onLine(rest);
        }
        resolve({ code, stdout, stderr, timedOut, aborted });
      }),
    );
  });
}
