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
  /** TODO(phase 2): the running job, once jobs exist. */
  active_job: string | null;
}

/** Node kinds that are not symbols, so they are left out of the `symbols` count. */
const NOT_SYMBOLS = new Set(['file', 'import']);

/**
 * Health and freshness of one project's code index.
 * A project that is not ready is a normal answer (200), never an error, so callers can poll it.
 */
export function buildStatus(p: ReadyProject | NotReadyProject, commitSha: string | null): CodeStatus {
  const snapshot = snapshotOf(p, commitSha);

  if (!p.ready) {
    const base = { snapshot, last_synced_sha: null, last_sync: null, index_lag_seconds: null, active_job: null };
    switch (p.reason) {
      case 'not_indexed':
        return { ...base, state: 'not_indexed', error: null };
      case 'indexing':
        return { ...base, state: 'indexing', error: null };
      case 'failed':
        return { ...base, state: 'error', error: 'The last index run failed' };
      case 'open_failed':
        return { ...base, state: 'error', error: 'The index could not be opened' };
    }
  }

  const stats = p.cg.getStats();
  let symbols = 0;
  for (const [kind, count] of Object.entries(stats.nodesByKind)) {
    if (!NOT_SYMBOLS.has(kind)) symbols += count;
  }
  return {
    state: 'ready',
    snapshot,
    last_synced_sha: commitSha,
    last_sync: snapshot.index_time,
    index_lag_seconds: null,
    files: stats.fileCount,
    symbols,
    edges: stats.edgeCount,
    error: null,
    active_job: null,
  };
}
