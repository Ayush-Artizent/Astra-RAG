import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { JobStore } from '../src/jobs/store.js';
import { DatabaseSync } from '../src/sqlite.js';

const stores: JobStore[] = [];
const dirs: string[] = [];
afterEach(() => {
  for (const s of stores.splice(0)) {
    try {
      s.close();
    } catch {
      // already closed
    }
  }
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

function memoryStore() {
  let clock = 1_000;
  const store = new JobStore(':memory:', () => clock);
  stores.push(store);
  return { store, tick: (ms = 10) => (clock += ms) };
}

const sync = (orgId = 'orgA', projectId = 'p1', commitSha = 'a'.repeat(40)) => ({ orgId, projectId, type: 'sync' as const, commitSha });

describe('jobs', () => {
  it('creates queued jobs with an opaque id', () => {
    const { store } = memoryStore();
    const job = store.create(sync());
    expect(job.id).toMatch(/^job_[0-9a-f]{32}$/);
    expect(job).toMatchObject({ state: 'queued', type: 'sync', orgId: 'orgA', projectId: 'p1', commitSha: 'a'.repeat(40), error: null, startedAt: null });
    expect(store.create(sync()).id).not.toBe(job.id);
  });

  it('only returns a job to the org and project that own it', () => {
    const { store } = memoryStore();
    const job = store.create(sync('orgA', 'p1'));
    expect(store.getScoped(job.id, 'orgA', 'p1')?.id).toBe(job.id);
    expect(store.getScoped(job.id, 'orgB', 'p1')).toBeUndefined();
    expect(store.getScoped(job.id, 'orgA', 'p2')).toBeUndefined();
    expect(store.getScoped('job_missing', 'orgA', 'p1')).toBeUndefined();
  });

  it('keeps idempotency keys per org and project', () => {
    const { store } = memoryStore();
    const a = store.create({ ...sync('orgA', 'p1'), idempotencyKey: 'k1', requestHash: 'h' });
    expect(store.findByIdempotencyKey('orgA', 'p1', 'k1')?.id).toBe(a.id);
    expect(store.findByIdempotencyKey('orgB', 'p1', 'k1')).toBeUndefined();
    expect(store.findByIdempotencyKey('orgA', 'p2', 'k1')).toBeUndefined();
    // The same key in another project is fine; the same key twice in one project is rejected by the database.
    expect(() => store.create({ ...sync('orgB', 'p1'), idempotencyKey: 'k1' })).not.toThrow();
    expect(() => store.create({ ...sync('orgA', 'p1'), idempotencyKey: 'k1' })).toThrow();
    // Jobs without a key never collide.
    expect(() => {
      store.create(sync());
      store.create(sync());
    }).not.toThrow();
  });

  it('lists active jobs of a project in creation order', () => {
    const { store, tick } = memoryStore();
    const first = store.create(sync());
    tick();
    const second = store.create(sync());
    store.create(sync('orgA', 'other'));
    store.update(first.id, { state: 'done' });
    expect(store.activeForProject('orgA', 'p1').map((j) => j.id)).toEqual([second.id]);
    store.update(first.id, { state: 'running' });
    expect(store.activeForProject('orgA', 'p1').map((j) => j.id)).toEqual([first.id, second.id]);
  });

  it('updates only the fields given, and can clear one with null', () => {
    const { store } = memoryStore();
    const job = store.create(sync());
    store.update(job.id, { state: 'running', phase: 'parsing', progress: 0.4, startedAt: 5 });
    expect(store.get(job.id)).toMatchObject({ state: 'running', phase: 'parsing', progress: 0.4, startedAt: 5 });
    store.update(job.id, { progress: undefined });
    expect(store.get(job.id)?.progress).toBe(0.4);
    store.update(job.id, { phase: null });
    expect(store.get(job.id)?.phase).toBeNull();
    expect(() => store.update(job.id, {})).not.toThrow();
  });

  it('supersedes only queued syncs of the same project, and records which job replaced them', () => {
    const { store } = memoryStore();
    const old1 = store.create(sync('orgA', 'p1', '1'.repeat(40)));
    const old2 = store.create(sync('orgA', 'p1', '2'.repeat(40)));
    const running = store.create(sync('orgA', 'p1', '3'.repeat(40)));
    store.update(running.id, { state: 'running' });
    const otherProject = store.create(sync('orgA', 'p2'));
    const otherOrg = store.create(sync('orgB', 'p1'));
    const bootstrap = store.create({ orgId: 'orgA', projectId: 'p1', type: 'bootstrap' });
    const newest = store.create(sync('orgA', 'p1', '4'.repeat(40)));

    const ids = store.supersedeQueuedSyncs('orgA', 'p1', newest.id);

    expect(ids.sort()).toEqual([old1.id, old2.id].sort());
    expect(store.get(old1.id)).toMatchObject({ state: 'superseded', coalescedInto: newest.id });
    expect(store.get(old1.id)?.finishedAt).not.toBeNull();
    expect(store.get(running.id)?.state).toBe('running'); // never interrupted
    expect(store.get(otherProject.id)?.state).toBe('queued');
    expect(store.get(otherOrg.id)?.state).toBe('queued');
    expect(store.get(bootstrap.id)?.state).toBe('queued');
    expect(store.get(newest.id)?.state).toBe('queued');
  });

  it('points every replaced sync at the newest job, not at a chain of replaced ones', () => {
    const { store } = memoryStore();
    const first = store.create(sync('orgA', 'p1', '1'.repeat(40)));
    const second = store.create(sync('orgA', 'p1', '2'.repeat(40)));
    store.supersedeQueuedSyncs('orgA', 'p1', second.id); // first -> second
    const third = store.create(sync('orgA', 'p1', '3'.repeat(40)));
    store.supersedeQueuedSyncs('orgA', 'p1', third.id); // second -> third, and first must follow
    expect(store.get(first.id)).toMatchObject({ state: 'superseded', coalescedInto: third.id });
    expect(store.get(second.id)).toMatchObject({ state: 'superseded', coalescedInto: third.id });
    expect(store.get(third.id)?.coalescedInto).toBeNull();
  });

  it('marks jobs left running by a dead process as failed', () => {
    const { store } = memoryStore();
    const a = store.create(sync());
    const b = store.create(sync('orgA', 'p2'));
    store.update(a.id, { state: 'running' });
    const interrupted = store.failInterruptedJobs('restarted');
    expect(interrupted.map((j) => j.id)).toEqual([a.id]);
    expect(interrupted[0]).toMatchObject({ state: 'failed', error: 'restarted' });
    expect(store.get(a.id)).toMatchObject({ state: 'failed', error: 'restarted' });
    expect(store.get(b.id)?.state).toBe('queued');
    expect(store.running()).toEqual([]);
  });
});

describe('projects', () => {
  const binding = { orgId: 'orgA', projectId: 'p1', repoUrl: 'https://github.com/a/b', branch: 'main', credentialsRef: 'acme' };

  it('adds a binding once, then reports it already exists', () => {
    const { store } = memoryStore();
    expect(store.addProject(binding)).toBe(true);
    expect(store.addProject({ ...binding, repoUrl: 'https://github.com/other/repo' })).toBe(false);
    expect(store.getProject('orgA', 'p1')).toMatchObject({ repoUrl: 'https://github.com/a/b', branch: 'main', credentialsRef: 'acme', bootstrappedAt: null });
  });

  it('keeps bindings apart by org and project', () => {
    const { store } = memoryStore();
    store.addProject(binding);
    expect(store.getProject('orgB', 'p1')).toBeUndefined();
    expect(store.getProject('orgA', 'p2')).toBeUndefined();
    expect(store.addProject({ ...binding, orgId: 'orgB' })).toBe(true);
  });

  it('records when the first bootstrap finished and can forget a project', () => {
    const { store, tick } = memoryStore();
    store.addProject(binding);
    tick(500);
    store.markBootstrapped('orgA', 'p1');
    expect(store.getProject('orgA', 'p1')?.bootstrappedAt).toBe(1_500);
    store.deleteProject('orgA', 'p1');
    expect(store.getProject('orgA', 'p1')).toBeUndefined();
    expect(store.addProject(binding)).toBe(true);
  });
});

describe('freshness bookkeeping', () => {
  const bind = { orgId: 'orgA', projectId: 'p1', repoUrl: 'https://github.com/a/b', branch: null, credentialsRef: null };
  const A = 'a'.repeat(40);
  const B = 'b'.repeat(40);
  const C = 'c'.repeat(40);

  it('starts the lag clock on the first unindexed commit and keeps it while the remote moves further ahead', () => {
    const { store, tick } = memoryStore();
    store.addProject(bind);
    store.markBehind('orgA', 'p1', A);
    const started = store.getProject('orgA', 'p1')?.behindSince as number;
    expect(started).toBeGreaterThan(0);
    expect(store.getProject('orgA', 'p1')?.remoteHead).toBe(A);

    tick(5_000);
    store.markBehind('orgA', 'p1', B); // another push before the first was indexed
    expect(store.getProject('orgA', 'p1')).toMatchObject({ remoteHead: B, behindSince: started });
  });

  it('stops the clock only when the sync that finished is the newest known commit', () => {
    const { store } = memoryStore();
    store.addProject(bind);
    store.markBehind('orgA', 'p1', A);
    store.markBehind('orgA', 'p1', B);
    store.markCaughtUp('orgA', 'p1', A); // an older sync finished; the remote is already at B
    expect(store.getProject('orgA', 'p1')?.behindSince).not.toBeNull();
    store.markCaughtUp('orgA', 'p1', B);
    expect(store.getProject('orgA', 'p1')?.behindSince).toBeNull();
  });

  it('records a remote check: up to date clears the clock, behind starts or keeps it', () => {
    const { store, tick } = memoryStore();
    store.addProject(bind);
    store.noteRemoteHead('orgA', 'p1', A, A);
    expect(store.getProject('orgA', 'p1')).toMatchObject({ remoteHead: A, behindSince: null });
    expect(store.getProject('orgA', 'p1')?.remoteCheckedAt).toBeGreaterThan(0);

    store.noteRemoteHead('orgA', 'p1', B, A);
    const since = store.getProject('orgA', 'p1')?.behindSince as number;
    expect(since).toBeGreaterThan(0);
    tick(10_000);
    store.noteRemoteHead('orgA', 'p1', C, A);
    expect(store.getProject('orgA', 'p1')).toMatchObject({ remoteHead: C, behindSince: since });
    store.noteRemoteHead('orgA', 'p1', C, C);
    expect(store.getProject('orgA', 'p1')?.behindSince).toBeNull();
  });

  it('treats an index with no known commit as behind', () => {
    const { store } = memoryStore();
    store.addProject(bind);
    store.noteRemoteHead('orgA', 'p1', A, null);
    expect(store.getProject('orgA', 'p1')?.behindSince).not.toBeNull();
  });

  it('keeps projects apart', () => {
    const { store } = memoryStore();
    store.addProject(bind);
    store.addProject({ ...bind, orgId: 'orgB' });
    store.markBehind('orgA', 'p1', A);
    expect(store.getProject('orgB', 'p1')).toMatchObject({ remoteHead: null, behindSince: null });
  });

  it('tracks use, pruning and disk, and a bootstrap makes a pruned project whole again', () => {
    const { store, tick } = memoryStore();
    store.addProject(bind);
    expect(store.getProject('orgA', 'p1')).toMatchObject({ lastUsedAt: null, prunedAt: null, diskTreeBytes: null });

    store.touchProject('orgA', 'p1', 123);
    expect(store.getProject('orgA', 'p1')?.lastUsedAt).toBe(123);
    store.setDisk('orgA', 'p1', { tree: 10, git: 20, index: 30 });
    expect(store.getProject('orgA', 'p1')).toMatchObject({ diskTreeBytes: 10, diskGitBytes: 20, diskIndexBytes: 30 });
    expect(store.getProject('orgA', 'p1')?.diskMeasuredAt).toBeGreaterThan(0);

    store.markBehind('orgA', 'p1', A);
    tick();
    store.markPruned('orgA', 'p1');
    expect(store.getProject('orgA', 'p1')).toMatchObject({ behindSince: null, diskTreeBytes: null, diskMeasuredAt: null });
    expect(store.getProject('orgA', 'p1')?.prunedAt).toBeGreaterThan(0);

    store.markBootstrapped('orgA', 'p1');
    expect(store.getProject('orgA', 'p1')?.prunedAt).toBeNull();
    expect(store.getProject('orgA', 'p1')?.lastUsedAt).toBeGreaterThan(123);
  });

  it('lists every project in a stable order, and stores a job detail', () => {
    const { store } = memoryStore();
    store.addProject({ ...bind, orgId: 'orgB' });
    store.addProject(bind);
    store.addProject({ ...bind, projectId: 'a1' });
    expect(store.listProjects().map((p) => `${p.orgId}/${p.projectId}`)).toEqual(['orgA/a1', 'orgA/p1', 'orgB/p1']);
    const job = store.create({ orgId: 'orgA', projectId: 'p1', type: 'reconcile' });
    store.update(job.id, { detail: 'up to date at aaaaaaa' });
    expect(store.get(job.id)?.detail).toBe('up to date at aaaaaaa');
  });
});

describe('persistence and schema', () => {
  it('upgrades a file written by schema version 1 without losing anything', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-store-v1-'));
    dirs.push(dir);
    const file = path.join(dir, 'jobs.db');
    const old = new DatabaseSync(file);
    old.exec(`
      CREATE TABLE projects (org_id TEXT NOT NULL, project_id TEXT NOT NULL, repo_url TEXT NOT NULL, branch TEXT,
        credentials_ref TEXT, created_at INTEGER NOT NULL, bootstrapped_at INTEGER, PRIMARY KEY (org_id, project_id));
      CREATE TABLE jobs (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, project_id TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('bootstrap', 'sync', 'reconcile')),
        state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed', 'superseded')),
        commit_sha TEXT, phase TEXT, progress REAL, error TEXT, created_at INTEGER NOT NULL, started_at INTEGER,
        finished_at INTEGER, files INTEGER, symbols INTEGER, edges INTEGER, coalesced_into TEXT,
        idempotency_key TEXT, request_hash TEXT);
      INSERT INTO projects VALUES ('orgA', 'p1', 'https://github.com/a/b', 'main', 'acme', 5, 7);
      INSERT INTO jobs (id, org_id, project_id, type, state, created_at, files) VALUES ('job_old', 'orgA', 'p1', 'bootstrap', 'done', 5, 42);
      PRAGMA user_version = 1;
    `);
    old.close();

    const store = new JobStore(file);
    stores.push(store);
    expect(store.getProject('orgA', 'p1')).toMatchObject({
      repoUrl: 'https://github.com/a/b', branch: 'main', credentialsRef: 'acme', bootstrappedAt: 7,
      remoteHead: null, behindSince: null, lastUsedAt: null, prunedAt: null, diskTreeBytes: null,
    });
    expect(store.get('job_old')).toMatchObject({ state: 'done', files: 42, detail: null });
    // The new columns work on the old rows.
    store.markBehind('orgA', 'p1', 'a'.repeat(40));
    store.update('job_old', { detail: 'kept' });
    expect(store.getProject('orgA', 'p1')?.behindSince).toBeGreaterThan(0);
    expect(store.get('job_old')?.detail).toBe('kept');
    // Opening it again changes nothing.
    store.close();
    stores.pop();
    const again = new JobStore(file);
    stores.push(again);
    expect(again.get('job_old')?.files).toBe(42);
  });

  const tmp = () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-store-'));
    dirs.push(dir);
    return path.join(dir, 'nested', 'jobs.db');
  };

  it('creates its folder, and keeps jobs and projects across a reopen', () => {
    const file = tmp();
    const first = new JobStore(file);
    const job = first.create({ orgId: 'orgA', projectId: 'p1', type: 'bootstrap' });
    first.addProject({ orgId: 'orgA', projectId: 'p1', repoUrl: 'https://github.com/a/b', branch: null, credentialsRef: null });
    first.close();

    const second = new JobStore(file);
    stores.push(second);
    expect(second.get(job.id)?.state).toBe('queued');
    expect(second.getProject('orgA', 'p1')?.repoUrl).toBe('https://github.com/a/b');
  });

  it('refuses a file written by a newer adapter', () => {
    const file = tmp();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const raw = new DatabaseSync(file);
    raw.exec('PRAGMA user_version = 99');
    raw.close();
    expect(() => new JobStore(file)).toThrow(/newer adapter/);
  });

  it('uses write-ahead logging for a file database', () => {
    const file = tmp();
    const store = new JobStore(file);
    stores.push(store);
    // `readOnly` works at runtime on Node 22.12+ but is missing from the installed type definitions.
    const raw = new DatabaseSync(file, { readOnly: true } as unknown as ConstructorParameters<typeof DatabaseSync>[1]);
    const mode = (raw.prepare('PRAGMA journal_mode').get() as { journal_mode: string }).journal_mode;
    raw.close();
    expect(mode).toBe('wal');
  });
});
