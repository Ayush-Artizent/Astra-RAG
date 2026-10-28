import fs from 'node:fs';
import path from 'node:path';
import { openReadOnly } from '../codegraph.js';
import type { Config } from '../config.js';
import { projectDir } from '../paths.js';
import type { ProjectRegistry } from '../projects.js';
import { countSymbols } from '../status.js';
import type { runCodegraph } from './codegraph-cli.js';
import { resolveCredential } from './credentials.js';
import { measureDisk } from './disk.js';
import { gitEnvironment, headSha, samePath, topLevel } from './git.js';
import { readIndexedCommit } from './stamp.js';
import type { JobStore } from './store.js';
import type { ProjectBinding } from './types.js';
import { findSymlinks } from './workspace.js';

/** Measures a project's disk use and records it. Failures are ignored: the figure is informational. */
export async function measureAndStore(store: JobStore, orgId: string, projectId: string, dir: string): Promise<void> {
  try {
    const use = await measureDisk(dir);
    store.setDisk(orgId, projectId, use);
  } catch {
    // the store may be closed during shutdown, or the folder may be gone
  }
}

/** Everything the executors share. */
export interface JobEnvironment {
  config: Config;
  registry: ProjectRegistry;
  /** An empty file used as git's global config. */
  emptyGitConfig: string;
  /** Replaces the CodeGraph CLI. Tests use it to make indexing fail or wait at a chosen moment. */
  runCodegraph?: typeof runCodegraph;
}

/** Creates the empty git config file once. */
export function ensureEmptyGitConfig(dataDir: string): string {
  const file = path.join(dataDir, '.adapter', 'empty.gitconfig');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (!fs.existsSync(file)) fs.writeFileSync(file, '');
  return file;
}

export interface Prepared {
  dir: string;
  gitEnv: NodeJS.ProcessEnv;
  secrets: string[];
}

/** The project folder, the git environment for its repo, and the secrets to scrub from errors. */
export function prepare(env: JobEnvironment, project: ProjectBinding): Prepared {
  const credential = resolveCredential(project.credentialsRef);
  const gitEnv = gitEnvironment({
    allowFileRepos: env.config.allowFileRepos,
    credential,
    repoUrl: project.repoUrl,
    emptyConfigFile: env.emptyGitConfig,
  });
  return {
    dir: projectDir(env.config.dataDir, project.orgId, project.projectId),
    gitEnv,
    secrets: credential?.secrets ?? [],
  };
}

/** Counts down a total time budget shared by every step of a job. */
export function budget(totalMs: number, label: string): () => number {
  const end = Date.now() + totalMs;
  return () => {
    const left = end - Date.now();
    if (left <= 0) throw new Error(`${label} timed out after ${Math.round(totalMs / 1000)}s`);
    return left;
  };
}

/**
 * Checks a fresh or updated checkout before it is indexed: the folder must be the root of its own git working
 * tree (the commit stamp is the HEAD of whatever repo contains the folder), and must hold no real symlinks (the
 * indexer follows them out of the project). Returns the checked-out commit.
 */
export async function verifyCheckout(prepared: Prepared, timeoutMs: number, signal: AbortSignal): Promise<string> {
  const run = { env: prepared.gitEnv, timeoutMs, signal, secrets: prepared.secrets };
  const root = await topLevel(prepared.dir, run);
  if (!samePath(root, prepared.dir)) {
    throw new Error('The project folder is not the root of its own git repository');
  }
  const links = findSymlinks(prepared.dir);
  if (links.length > 0) {
    throw new Error(`The repository contains symbolic links, which are refused: ${links.slice(0, 5).join(', ')}`);
  }
  return headSha(prepared.dir, run);
}

export interface IndexSummary {
  files: number;
  symbols: number;
  edges: number;
}

/**
 * Opens the finished index and checks it: complete, and stamped with the commit that is checked out.
 * Returns its size for the job record.
 */
export async function summariseIndex(dir: string, expectedCommit: string): Promise<IndexSummary> {
  const cg = await openReadOnly(dir);
  try {
    const state = cg.getIndexState();
    if (state !== 'complete') throw new Error(`The index did not complete (state: ${state ?? 'unknown'})`);
    const stats = cg.getStats();
    const stamp = readIndexedCommit(dir);
    if (stamp !== expectedCommit) {
      throw new Error(`The index reports commit ${stamp ?? 'none'} but the checkout is at ${expectedCommit}`);
    }
    return { files: stats.fileCount, symbols: countSymbols(stats.nodesByKind), edges: stats.edgeCount };
  } finally {
    cg.close();
  }
}
