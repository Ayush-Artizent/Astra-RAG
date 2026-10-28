import type { ProjectBinding } from './jobs/types.js';
import type { NotReadyProject, ReadyProject } from './projects.js';
import { snapshotOf, type Snapshot } from './shape.js';

export type StatusState = 'not_indexed' | 'indexing' | 'ready' | 'error';

export interface DiskStatus {
  /** Source files of the working tree. */
  tree_bytes: number;
  /** The `.git` folder. */
  git_bytes: number;
  /** The index database and its log. */
  index_bytes: number;
  measured_at: string;
}

export interface CodeStatus {
  state: StatusState;
  snapshot: Snapshot;
  last_synced_sha: string | null;
  last_sync: string | null;
  /**
   * How long the index has been behind the remote, in seconds: 0 when it is up to date, null when the remote has
   * never been checked. Counts from the first push or check that found a commit the index did not have yet.
   */
  index_lag_seconds: number | null;
  files?: number;
  symbols?: number;
  edges?: number;
  error: string | null;
  /** The job running for this project, or else the next one queued. */
  active_job: string | null;
  /** Disk used by the project, measured after each sync and reconcile. Null until measured. */
  disk: DiskStatus | null;
  /** When idle pruning deleted the project's folder. The next query rebuilds it. Null if it was never pruned. */
  pruned_at: string | null;
}

/** Node kinds that are not symbols, so they are left out of the `symbols` count. */
const NOT_SYMBOLS = new Set(['file', 'import']);

/** Symbols in an index: every node except files and imports. */
export function countSymbols(nodesByKind: Record<string, number>): number {
  let total = 0;
  for (const [kind, count] of Object.entries(nodesByKind)) {
    if (!NOT_SYMBOLS.has(kind)) total += count;
  }
  return total;
}

/** The job that is running, or else the next one queued, for a project. */
export interface ActiveJob {
  id: string;
  running: boolean;
}

export interface StatusExtras {
  /** What the adapter remembers about the project: remote head, lag clock, disk use, pruning. */
  binding?: ProjectBinding;
  now?: number;
}

const iso = (ms: number | null | undefined): string | null => (ms === null || ms === undefined ? null : new Date(ms).toISOString());

function lagSeconds(binding: ProjectBinding | undefined, indexed: string | null, now: number): number | null {
  if (!binding?.remoteHead) return null;
  if (indexed !== null && binding.remoteHead === indexed) return 0;
  return binding.behindSince === null ? 0 : Math.max(0, Math.floor((now - binding.behindSince) / 1000));
}

function diskOf(binding: ProjectBinding | undefined): DiskStatus | null {
  if (!binding || binding.diskMeasuredAt === null) return null;
  return {
    tree_bytes: binding.diskTreeBytes ?? 0,
    git_bytes: binding.diskGitBytes ?? 0,
    index_bytes: binding.diskIndexBytes ?? 0,
    measured_at: iso(binding.diskMeasuredAt) as string,
  };
}

/**
 * Health and freshness of one project's code index.
 * A project that is not ready is a normal answer (200), never an error, so callers can poll it.
 * While a bootstrap is cloning (no index yet) the state is `indexing`, not `not_indexed`.
 */
export function buildStatus(
  p: ReadyProject | NotReadyProject,
  commitSha: string | null,
  active: ActiveJob | null = null,
  syncing = false,
  extras: StatusExtras = {},
): CodeStatus {
  const snapshot = snapshotOf(p, commitSha, syncing);
  const active_job = active?.id ?? null;
  const now = extras.now ?? Date.now();
  const pruned_at = iso(extras.binding?.prunedAt);

  if (!p.ready) {
    const base = {
      snapshot,
      last_synced_sha: null,
      last_sync: null,
      index_lag_seconds: null,
      active_job,
      disk: diskOf(extras.binding),
      pruned_at,
    };
    switch (p.reason) {
      case 'not_indexed':
        return { ...base, state: active ? 'indexing' : 'not_indexed', error: null };
      case 'indexing':
        return { ...base, state: 'indexing', error: null };
      case 'failed':
        return { ...base, state: 'error', error: 'The last index run failed' };
      case 'open_failed':
        return { ...base, state: 'error', error: 'The index could not be opened' };
    }
  }

  const stats = p.cg.getStats();
  return {
    state: 'ready',
    snapshot,
    last_synced_sha: commitSha,
    last_sync: snapshot.index_time,
    index_lag_seconds: lagSeconds(extras.binding, commitSha, now),
    files: stats.fileCount,
    symbols: countSymbols(stats.nodesByKind),
    edges: stats.edgeCount,
    error: null,
    active_job,
    disk: diskOf(extras.binding),
    pruned_at,
  };
}
