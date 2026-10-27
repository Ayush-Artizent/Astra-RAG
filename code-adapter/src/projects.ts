import { isInitialized, openReadOnly, type CodeGraph } from './codegraph.js';
import { projectDir } from './paths.js';

export type IndexState = 'indexing' | 'complete' | 'partial' | 'failed' | null;
export type NotReadyReason = 'not_indexed' | 'indexing' | 'failed' | 'open_failed';

export interface ReadyProject {
  ready: true;
  dir: string;
  cg: CodeGraph;
  indexState: IndexState;
  lastIndexedAt: number | null;
}

export interface NotReadyProject {
  ready: false;
  dir: string;
  reason: NotReadyReason;
  indexState: IndexState;
}

/** A borrowed project. The handle stays open until `release` is called, even if it is evicted meanwhile. */
export interface Lease {
  project: ReadyProject | NotReadyProject;
  release(): void;
}

/** The slice of CodeGraph the registry needs, so tests can substitute a fake. */
export type Handle = Pick<CodeGraph, 'getIndexState' | 'getLastIndexedAt' | 'close'>;

export interface RegistryOptions {
  dataDir: string;
  /** Handles kept open at once. Least recently used idle handles are closed beyond this. */
  maxOpen?: number;
  /** An idle handle is closed after this many milliseconds. 0 disables the sweep. */
  idleMs?: number;
  open?: (dir: string) => Promise<Handle>;
  initialized?: (dir: string) => boolean;
  now?: () => number;
}

interface Entry {
  dir: string;
  opening: Promise<Handle>;
  handle?: Handle;
  refs: number;
  lastUsed: number;
  retired: boolean;
}

/**
 * Caches one read-only CodeGraph handle per project.
 *
 * The directory comes from `projectDir`, the only path builder, so a handle can only be reached through
 * an org and project that passed envelope checks. Opening is the expensive step (0.3 to 1.1 s in the
 * spikes), so handles are reused and concurrent first requests share one open.
 */
export class ProjectRegistry {
  private readonly entries = new Map<string, Entry>();
  private readonly maxOpen: number;
  private readonly open: (dir: string) => Promise<Handle>;
  private readonly initialized: (dir: string) => boolean;
  private readonly now: () => number;
  private readonly timer?: NodeJS.Timeout;

  constructor(private readonly opts: RegistryOptions) {
    this.maxOpen = opts.maxOpen ?? 8;
    this.open = opts.open ?? openReadOnly;
    this.initialized = opts.initialized ?? isInitialized;
    this.now = opts.now ?? Date.now;
    const idleMs = opts.idleMs ?? 10 * 60_000;
    if (idleMs > 0) {
      this.timer = setInterval(() => this.sweepIdle(idleMs), Math.min(idleMs, 60_000));
      this.timer.unref();
    }
  }

  get openCount(): number {
    return this.entries.size;
  }

  async acquire(orgId: string, projectId: string): Promise<Lease> {
    const dir = projectDir(this.opts.dataDir, orgId, projectId);

    if (!this.initialized(dir)) {
      // The index is gone (or never existed). Drop any handle that still points at the old files.
      this.retireDir(dir);
      return this.notReady(dir, 'not_indexed', null);
    }

    let entry = this.entries.get(dir);
    if (!entry) {
      const created: Entry = {
        dir,
        opening: this.open(dir),
        refs: 0,
        lastUsed: this.now(),
        retired: false,
      };
      // Failed opens are never cached, so the next request retries.
      created.opening.catch(() => {
        if (this.entries.get(dir) === created) this.entries.delete(dir);
      });
      this.entries.set(dir, created);
      entry = created;
    }

    entry.refs++;
    entry.lastUsed = this.now();
    let handle: Handle;
    try {
      handle = await entry.opening;
      entry.handle = handle;
    } catch {
      entry.refs--;
      return this.notReady(dir, 'open_failed', null);
    }

    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      entry.refs--;
      entry.lastUsed = this.now();
      if (entry.retired && entry.refs === 0) this.closeQuietly(handle);
    };

    const indexState = handle.getIndexState();
    const lastIndexedAt = handle.getLastIndexedAt();
    const reason = this.notReadyReason(indexState, lastIndexedAt);
    if (reason) {
      release();
      return this.notReady(dir, reason, indexState);
    }

    this.enforceCapacity();
    return {
      project: { ready: true, dir, cg: handle as CodeGraph, indexState, lastIndexedAt },
      release,
    };
  }

  /**
   * Closes the handle for a project. Call before anything replaces or deletes its index files
   * (a rebuild from git): on Windows an open database file cannot be removed.
   */
  evict(orgId: string, projectId: string): void {
    this.retireDir(projectDir(this.opts.dataDir, orgId, projectId));
  }

  closeAll(): void {
    if (this.timer) clearInterval(this.timer);
    for (const dir of [...this.entries.keys()]) this.retireDir(dir);
  }

  /** Closes idle handles unused for longer than `idleMs`. Runs on a timer; exposed for tests. */
  sweepIdle(idleMs: number): void {
    const cutoff = this.now() - idleMs;
    for (const entry of [...this.entries.values()]) {
      if (entry.refs === 0 && entry.lastUsed <= cutoff) this.retire(entry);
    }
  }

  private notReadyReason(indexState: IndexState, lastIndexedAt: number | null): NotReadyReason | undefined {
    // Only a full index run writes `indexing`, so it means the on-disk data is truncated. A sync does not.
    if (indexState === 'indexing') return 'indexing';
    if (indexState === 'failed') return 'failed';
    if (indexState === null && lastIndexedAt === null) return 'not_indexed';
    return undefined;
  }

  private notReady(dir: string, reason: NotReadyReason, indexState: IndexState): Lease {
    return { project: { ready: false, dir, reason, indexState }, release: () => {} };
  }

  private enforceCapacity(): void {
    if (this.entries.size <= this.maxOpen) return;
    const idle = [...this.entries.values()]
      .filter((e) => e.refs === 0)
      .sort((a, b) => a.lastUsed - b.lastUsed);
    for (const entry of idle) {
      if (this.entries.size <= this.maxOpen) break;
      this.retire(entry);
    }
  }

  private retireDir(dir: string): void {
    const entry = this.entries.get(dir);
    if (entry) this.retire(entry);
  }

  private retire(entry: Entry): void {
    if (this.entries.get(entry.dir) === entry) this.entries.delete(entry.dir);
    entry.retired = true;
    if (entry.refs === 0) {
      const handle = entry.handle;
      if (handle) this.closeQuietly(handle);
      else entry.opening.then((h) => this.closeQuietly(h), () => {});
    }
  }

  private closeQuietly(handle: Handle): void {
    try {
      handle.close();
    } catch {
      // nothing useful to do if a read-only handle fails to close
    }
  }
}
