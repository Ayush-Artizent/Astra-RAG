import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { DatabaseSync, type Database } from '../sqlite.js';
import type { JobPhase, JobRow, JobState, NewJob, ProjectBinding } from './types.js';

const SCHEMA_VERSION = 2;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS projects (
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  repo_url TEXT NOT NULL,
  branch TEXT,
  credentials_ref TEXT,
  created_at INTEGER NOT NULL,
  bootstrapped_at INTEGER,
  remote_head TEXT,
  remote_checked_at INTEGER,
  behind_since INTEGER,
  last_used_at INTEGER,
  pruned_at INTEGER,
  disk_tree_bytes INTEGER,
  disk_git_bytes INTEGER,
  disk_index_bytes INTEGER,
  disk_measured_at INTEGER,
  PRIMARY KEY (org_id, project_id)
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('bootstrap', 'sync', 'reconcile')),
  state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed', 'superseded')),
  commit_sha TEXT,
  phase TEXT,
  progress REAL,
  error TEXT,
  detail TEXT,
  created_at INTEGER NOT NULL,
  started_at INTEGER,
  finished_at INTEGER,
  files INTEGER,
  symbols INTEGER,
  edges INTEGER,
  coalesced_into TEXT,
  idempotency_key TEXT,
  request_hash TEXT
);
CREATE INDEX IF NOT EXISTS jobs_by_project ON jobs (org_id, project_id, state);
CREATE INDEX IF NOT EXISTS jobs_by_state ON jobs (state, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency
  ON jobs (org_id, project_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
`;

/** Columns added after version 1. A file written by version 1 gets them on open. */
const ADDED_IN_V2: Array<[table: string, column: string, type: string]> = [
  ['projects', 'remote_head', 'TEXT'],
  ['projects', 'remote_checked_at', 'INTEGER'],
  ['projects', 'behind_since', 'INTEGER'],
  ['projects', 'last_used_at', 'INTEGER'],
  ['projects', 'pruned_at', 'INTEGER'],
  ['projects', 'disk_tree_bytes', 'INTEGER'],
  ['projects', 'disk_git_bytes', 'INTEGER'],
  ['projects', 'disk_index_bytes', 'INTEGER'],
  ['projects', 'disk_measured_at', 'INTEGER'],
  ['jobs', 'detail', 'TEXT'],
];

interface Raw {
  [column: string]: string | number | null;
}

const toJob = (r: Raw): JobRow => ({
  id: r.id as string,
  orgId: r.org_id as string,
  projectId: r.project_id as string,
  type: r.type as JobRow['type'],
  state: r.state as JobState,
  commitSha: r.commit_sha as string | null,
  phase: r.phase as JobPhase | null,
  progress: r.progress as number | null,
  error: r.error as string | null,
  detail: r.detail as string | null,
  createdAt: r.created_at as number,
  startedAt: r.started_at as number | null,
  finishedAt: r.finished_at as number | null,
  files: r.files as number | null,
  symbols: r.symbols as number | null,
  edges: r.edges as number | null,
  coalescedInto: r.coalesced_into as string | null,
  idempotencyKey: r.idempotency_key as string | null,
  requestHash: r.request_hash as string | null,
});

const toProject = (r: Raw): ProjectBinding => ({
  orgId: r.org_id as string,
  projectId: r.project_id as string,
  repoUrl: r.repo_url as string,
  branch: r.branch as string | null,
  credentialsRef: r.credentials_ref as string | null,
  createdAt: r.created_at as number,
  bootstrappedAt: r.bootstrapped_at as number | null,
  remoteHead: r.remote_head as string | null,
  remoteCheckedAt: r.remote_checked_at as number | null,
  behindSince: r.behind_since as number | null,
  lastUsedAt: r.last_used_at as number | null,
  prunedAt: r.pruned_at as number | null,
  diskTreeBytes: r.disk_tree_bytes as number | null,
  diskGitBytes: r.disk_git_bytes as number | null,
  diskIndexBytes: r.disk_index_bytes as number | null,
  diskMeasuredAt: r.disk_measured_at as number | null,
});

/** Columns a job update may change. */
export interface JobPatch {
  state?: JobState;
  phase?: JobPhase | null;
  progress?: number | null;
  error?: string | null;
  detail?: string | null;
  startedAt?: number | null;
  finishedAt?: number | null;
  files?: number | null;
  symbols?: number | null;
  edges?: number | null;
  commitSha?: string | null;
  coalescedInto?: string | null;
}

const COLUMN: Record<keyof JobPatch, string> = {
  state: 'state',
  phase: 'phase',
  progress: 'progress',
  error: 'error',
  detail: 'detail',
  startedAt: 'started_at',
  finishedAt: 'finished_at',
  files: 'files',
  symbols: 'symbols',
  edges: 'edges',
  commitSha: 'commit_sha',
  coalescedInto: 'coalesced_into',
};

/**
 * The adapter's own record of jobs and of each project's repo binding (work plan, decision 2).
 * It does not store which commit an index reflects: that is read from the index (decision 6).
 */
export class JobStore {
  private readonly db: Database;
  private readonly now: () => number;

  constructor(file: string, now: () => number = Date.now) {
    if (file !== ':memory:') fs.mkdirSync(path.dirname(file), { recursive: true });
    this.db = new DatabaseSync(file);
    this.now = now;
    try {
      if (file !== ':memory:') this.db.exec('PRAGMA journal_mode = WAL');
      this.db.exec('PRAGMA busy_timeout = 5000');
      const version = (this.db.prepare('PRAGMA user_version').get() as { user_version: number }).user_version;
      if (version > SCHEMA_VERSION) {
        throw new Error(`The job store was written by a newer adapter (schema ${version}, this one is ${SCHEMA_VERSION})`);
      }
      this.db.exec(SCHEMA);
      this.addMissingColumns();
      this.db.exec(`PRAGMA user_version = ${SCHEMA_VERSION}`);
    } catch (e) {
      // Release the file before failing: an open handle makes the file undeletable on Windows.
      this.db.close();
      throw e;
    }
  }

  /** Brings a file written by an older adapter up to the current columns. Does nothing for a new file. */
  private addMissingColumns(): void {
    for (const [table, column, type] of ADDED_IN_V2) {
      const have = (this.db.prepare(`PRAGMA table_info(${table})`).all() as Raw[]).some((c) => c.name === column);
      if (!have) this.db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${type}`);
    }
  }

  close(): void {
    this.db.close();
  }

  // ---- projects ----------------------------------------------------------------------------

  getProject(orgId: string, projectId: string): ProjectBinding | undefined {
    const row = this.db.prepare('SELECT * FROM projects WHERE org_id = ? AND project_id = ?').get(orgId, projectId);
    return row ? toProject(row as Raw) : undefined;
  }

  listProjects(): ProjectBinding[] {
    return (this.db.prepare('SELECT * FROM projects ORDER BY org_id, project_id').all() as Raw[]).map(toProject);
  }

  /** Returns false if the project already has a binding. */
  addProject(p: Pick<ProjectBinding, 'orgId' | 'projectId' | 'repoUrl' | 'branch' | 'credentialsRef'>): boolean {
    const r = this.db
      .prepare(
        `INSERT OR IGNORE INTO projects (org_id, project_id, repo_url, branch, credentials_ref, created_at)
         VALUES (?, ?, ?, ?, ?, ?)`,
      )
      .run(p.orgId, p.projectId, p.repoUrl, p.branch, p.credentialsRef, this.now());
    return Number(r.changes) === 1;
  }

  /** The first (or a repeated, after a rebuild) bootstrap finished. A pruned project is whole again. */
  markBootstrapped(orgId: string, projectId: string): void {
    this.db
      .prepare('UPDATE projects SET bootstrapped_at = ?, pruned_at = NULL, last_used_at = ? WHERE org_id = ? AND project_id = ?')
      .run(this.now(), this.now(), orgId, projectId);
  }

  deleteProject(orgId: string, projectId: string): void {
    this.db.prepare('DELETE FROM projects WHERE org_id = ? AND project_id = ?').run(orgId, projectId);
  }

  /** A sync was requested to `commitSha`, so the remote is at least that far ahead. The lag clock starts. */
  markBehind(orgId: string, projectId: string, commitSha: string): void {
    this.db
      .prepare(
        `UPDATE projects SET remote_head = ?, behind_since = COALESCE(behind_since, ?)
         WHERE org_id = ? AND project_id = ?`,
      )
      .run(commitSha, this.now(), orgId, projectId);
  }

  /** A sync to `commitSha` finished. If that is still the newest known commit, the lag clock stops. */
  markCaughtUp(orgId: string, projectId: string, commitSha: string): void {
    this.db
      .prepare('UPDATE projects SET behind_since = NULL WHERE org_id = ? AND project_id = ? AND remote_head = ?')
      .run(orgId, projectId, commitSha);
  }

  /** Records what the remote says its head is, against the commit the index reflects. */
  noteRemoteHead(orgId: string, projectId: string, remoteHead: string, indexedCommit: string | null): void {
    const t = this.now();
    if (remoteHead === indexedCommit) {
      this.db
        .prepare('UPDATE projects SET remote_head = ?, remote_checked_at = ?, behind_since = NULL WHERE org_id = ? AND project_id = ?')
        .run(remoteHead, t, orgId, projectId);
    } else {
      this.db
        .prepare(
          `UPDATE projects SET remote_head = ?, remote_checked_at = ?, behind_since = COALESCE(behind_since, ?)
           WHERE org_id = ? AND project_id = ?`,
        )
        .run(remoteHead, t, t, orgId, projectId);
    }
  }

  /** Notes that the project was used. Pass a time to set it explicitly (tests). */
  touchProject(orgId: string, projectId: string, at: number = this.now()): void {
    this.db.prepare('UPDATE projects SET last_used_at = ? WHERE org_id = ? AND project_id = ?').run(at, orgId, projectId);
  }

  markPruned(orgId: string, projectId: string): void {
    this.db
      .prepare(
        `UPDATE projects SET pruned_at = ?, behind_since = NULL, disk_tree_bytes = NULL, disk_git_bytes = NULL,
           disk_index_bytes = NULL, disk_measured_at = NULL WHERE org_id = ? AND project_id = ?`,
      )
      .run(this.now(), orgId, projectId);
  }

  setDisk(orgId: string, projectId: string, bytes: { tree: number; git: number; index: number }): void {
    this.db
      .prepare(
        `UPDATE projects SET disk_tree_bytes = ?, disk_git_bytes = ?, disk_index_bytes = ?, disk_measured_at = ?
         WHERE org_id = ? AND project_id = ?`,
      )
      .run(bytes.tree, bytes.git, bytes.index, this.now(), orgId, projectId);
  }

  // ---- jobs --------------------------------------------------------------------------------

  create(job: NewJob): JobRow {
    const id = `job_${randomUUID().replace(/-/g, '')}`;
    this.db
      .prepare(
        `INSERT INTO jobs (id, org_id, project_id, type, state, commit_sha, created_at, idempotency_key, request_hash)
         VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)`,
      )
      .run(id, job.orgId, job.projectId, job.type, job.commitSha ?? null, this.now(), job.idempotencyKey ?? null, job.requestHash ?? null);
    return this.get(id) as JobRow;
  }

  get(id: string): JobRow | undefined {
    const row = this.db.prepare('SELECT * FROM jobs WHERE id = ?').get(id);
    return row ? toJob(row as Raw) : undefined;
  }

  /** A job, but only if it belongs to this org and project. Anything else looks like "not found". */
  getScoped(id: string, orgId: string, projectId: string): JobRow | undefined {
    const row = this.db
      .prepare('SELECT * FROM jobs WHERE id = ? AND org_id = ? AND project_id = ?')
      .get(id, orgId, projectId);
    return row ? toJob(row as Raw) : undefined;
  }

  findByIdempotencyKey(orgId: string, projectId: string, key: string): JobRow | undefined {
    const row = this.db
      .prepare('SELECT * FROM jobs WHERE org_id = ? AND project_id = ? AND idempotency_key = ?')
      .get(orgId, projectId, key);
    return row ? toJob(row as Raw) : undefined;
  }

  /** Queued and running jobs of a project, oldest first. */
  activeForProject(orgId: string, projectId: string): JobRow[] {
    return (
      this.db
        .prepare(
          `SELECT * FROM jobs WHERE org_id = ? AND project_id = ? AND state IN ('queued', 'running')
           ORDER BY created_at, rowid`,
        )
        .all(orgId, projectId) as Raw[]
    ).map(toJob);
  }

  /** A project's most recent jobs, newest first. */
  recentJobs(orgId: string, projectId: string, limit = 20): JobRow[] {
    return (
      this.db
        .prepare('SELECT * FROM jobs WHERE org_id = ? AND project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?')
        .all(orgId, projectId, limit) as Raw[]
    ).map(toJob);
  }

  queued(): JobRow[] {
    return (
      this.db.prepare(`SELECT * FROM jobs WHERE state = 'queued' ORDER BY created_at, rowid`).all() as Raw[]
    ).map(toJob);
  }

  running(): JobRow[] {
    return (this.db.prepare(`SELECT * FROM jobs WHERE state = 'running'`).all() as Raw[]).map(toJob);
  }

  update(id: string, patch: JobPatch): void {
    const entries = (Object.keys(patch) as (keyof JobPatch)[]).filter((k) => patch[k] !== undefined);
    if (entries.length === 0) return;
    const sets = entries.map((k) => `${COLUMN[k]} = ?`).join(', ');
    const values = entries.map((k) => patch[k] as string | number | null);
    this.db.prepare(`UPDATE jobs SET ${sets} WHERE id = ?`).run(...values, id);
  }

  /**
   * Marks every queued sync of the project, except `keepId`, as superseded by `keepId`.
   * A running sync is never touched. Returns the ids that were superseded.
   */
  supersedeQueuedSyncs(orgId: string, projectId: string, keepId: string): string[] {
    const ids = (
      this.db
        .prepare(
          `SELECT id FROM jobs WHERE org_id = ? AND project_id = ? AND type = 'sync' AND state = 'queued' AND id <> ?`,
        )
        .all(orgId, projectId, keepId) as Raw[]
    ).map((r) => r.id as string);
    for (const id of ids) {
      this.update(id, { state: 'superseded', coalescedInto: keepId, finishedAt: this.now() });
      // Jobs that were folded into this one earlier now point at the newest job, so a caller always sees
      // the job that will actually run, not a chain of replaced ones.
      this.db.prepare('UPDATE jobs SET coalesced_into = ? WHERE coalesced_into = ?').run(keepId, id);
    }
    return ids;
  }

  /** After a restart no job can still be running. Marks them failed and returns them, so they can be cleaned up. */
  failInterruptedJobs(message: string): JobRow[] {
    const interrupted = this.running();
    for (const job of interrupted) {
      this.update(job.id, { state: 'failed', error: message, finishedAt: this.now() });
    }
    return interrupted.map((j) => this.get(j.id) as JobRow);
  }
}
