import fs from 'node:fs';
import path from 'node:path';
import type { Credential } from './credentials.js';
import { runProcess } from './process.js';
import { scrubText } from './scrub.js';

export class GitError extends Error {}

export interface GitEnvOptions {
  /** Lets git use `file://` URLs. Tests only. */
  allowFileRepos: boolean;
  credential: Credential | null;
  /** The remote the credential is for. The Authorization header is sent only to this origin. */
  repoUrl: string | null;
  /** An empty file used as the global git config, so nobody's personal settings apply. */
  emptyConfigFile: string;
}

/**
 * The environment for every git command the adapter runs.
 *
 * - Nothing is inherited from the machine's git setup: no system or user config (so no credential helper that
 *   could pop up a login window), no GIT_* variables such as GIT_DIR that could redirect a command.
 * - Only https (and file in tests) transports are allowed, also for anything git starts itself.
 * - It never asks a question on a terminal.
 * - The token travels as an HTTP header set through environment variables scoped to the repo's origin, so it is
 *   never in a URL, in `.git/config`, or in the command line where other processes could read it.
 */
export function gitEnvironment(o: GitEnvOptions, base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(base)) {
    if (!key.toUpperCase().startsWith('GIT_') && value !== undefined) env[key] = value;
  }
  Object.assign(env, {
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_CONFIG_GLOBAL: o.emptyConfigFile,
    GIT_ALLOW_PROTOCOL: o.allowFileRepos ? 'https:file' : 'https',
    GIT_TERMINAL_PROMPT: '0',
    GCM_INTERACTIVE: 'never',
    GIT_PAGER: 'cat',
    LC_ALL: 'C',
  });
  if (o.credential && o.repoUrl) {
    const url = new URL(o.repoUrl);
    if (url.protocol === 'https:') {
      env.GIT_CONFIG_COUNT = '1';
      env.GIT_CONFIG_KEY_0 = `http.${url.origin}/.extraheader`;
      env.GIT_CONFIG_VALUE_0 = o.credential.header;
    }
  }
  return env;
}

export interface GitRun {
  cwd?: string;
  env: NodeJS.ProcessEnv;
  timeoutMs: number;
  signal?: AbortSignal;
  /** Secrets to remove from any error text. */
  secrets?: readonly string[];
}

/** The git subcommand in an argument list, skipping `-c name=value` pairs, for error messages. */
export function subcommand(args: readonly string[]): string {
  for (let i = 0; i < args.length; i++) {
    const arg = args[i] as string;
    if (arg === '-c') {
      i++; // its value
      continue;
    }
    if (!arg.startsWith('-')) return arg;
  }
  return 'command';
}

/** Runs one git command and returns its trimmed stdout. */
export async function git(args: readonly string[], run: GitRun): Promise<string> {
  // Never let git read the repo's own config for things that run programs.
  const safeArgs = ['-c', 'credential.helper=', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=', ...args];
  const what = subcommand(args);
  const result = await runProcess('git', safeArgs, { cwd: run.cwd, env: run.env, timeoutMs: run.timeoutMs, signal: run.signal });
  if (result.aborted) throw new Error('Cancelled');
  if (result.timedOut) throw new GitError(`git ${what} timed out after ${Math.round(run.timeoutMs / 1000)}s`);
  if (result.code !== 0) {
    const detail = scrubText(result.stderr.trim() || result.stdout.trim(), run.secrets ?? []);
    throw new GitError(`git ${what} failed (exit ${result.code}): ${detail}`);
  }
  return result.stdout.trim();
}

export interface CloneOptions extends GitRun {
  url: string;
  dir: string;
  branch: string | null;
}

/**
 * A shallow clone of one branch. Symlinks are written as plain files (`core.symlinks=false`), because the
 * indexer follows a symlink out of the project, which would let a repo pull in another tenant's files.
 * The setting is also saved in the clone's own config, so later `reset --hard` calls obey it.
 */
export async function cloneShallow(o: CloneOptions): Promise<void> {
  const args = [
    '-c', 'core.symlinks=false',
    '-c', 'core.autocrlf=false',
    'clone', '--depth', '1', '--no-tags', '--no-recurse-submodules',
    ...(o.branch ? ['--branch', o.branch] : []),
    '--', o.url, o.dir,
  ];
  await git(args, { env: o.env, timeoutMs: o.timeoutMs, signal: o.signal, secrets: o.secrets });
  await git(['config', 'core.symlinks', 'false'], { cwd: o.dir, env: o.env, timeoutMs: 30_000, signal: o.signal });
  await git(['config', 'core.autocrlf', 'false'], { cwd: o.dir, env: o.env, timeoutMs: 30_000, signal: o.signal });
}

export const headSha = (dir: string, run: Omit<GitRun, 'cwd'>) => git(['rev-parse', 'HEAD'], { ...run, cwd: dir });

/** The directory git considers the root of the working tree that contains `dir`. */
export const topLevel = (dir: string, run: Omit<GitRun, 'cwd'>) => git(['rev-parse', '--show-toplevel'], { ...run, cwd: dir });

/**
 * Whether two paths are the same directory. Compares real paths, because git reports the long form of a Windows
 * path (`C:/Users/alice/...`) while the folder may be spelled in its 8.3 short form (`C:\Users\ALICE~1\...`) or
 * through a link. Falls back to a plain comparison for paths that do not exist.
 */
export function samePath(a: string, b: string): boolean {
  const norm = (p: string) => {
    let r: string;
    try {
      r = fs.realpathSync.native(p);
    } catch {
      r = path.resolve(p);
    }
    return process.platform === 'win32' ? r.toLowerCase() : r;
  };
  return norm(a) === norm(b);
}
