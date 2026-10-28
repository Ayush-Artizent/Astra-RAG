import type { NotReadyProject, ReadyProject } from './projects.js';
import { snapshotOf, type Snapshot } from './shape.js';

export type StatusState = 'not_indexed' | 'indexing' | 'ready' | 'error';

export interface CodeStatus {
  state: StatusState;
  snapshot: Snapshot;
  last_synced_sha: string | null;
  last_sync: string | null;
  /** TODO(phase 2): needs the branch head from the reconcile job. */
  index_lag_seconds: number | null;
  files?: number;
  symbols?: number;
  edges?: number;
  error: string | null;
  /** The job running for this project, or else the next one queued. */
  active_job: string | null;
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
): CodeStatus {
  const snapshot = snapshotOf(p, commitSha, syncing);
  const active_job = active?.id ?? null;

  if (!p.ready) {
    const base = { snapshot, last_synced_sha: null, last_sync: null, index_lag_seconds: null, active_job };
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
    index_lag_seconds: null,
    files: stats.fileCount,
    symbols: countSymbols(stats.nodesByKind),
    edges: stats.edgeCount,
    error: null,
    active_job,
  };
}
