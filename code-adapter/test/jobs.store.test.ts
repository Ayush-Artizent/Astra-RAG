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

describe('persistence and schema', () => {
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
