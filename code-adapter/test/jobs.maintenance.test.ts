import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { measureDisk } from '../src/jobs/disk.js';
import { Maintenance } from '../src/jobs/maintenance.js';
import { JobQueue } from '../src/jobs/queue.js';
import { JobService } from '../src/jobs/service.js';
import { JobStore } from '../src/jobs/store.js';
import type { Executor } from '../src/jobs/types.js';
import type { ReadyProject } from '../src/projects.js';
import { buildStatus } from '../src/status.js';
import { binding } from './helpers.js';

const stores: JobStore[] = [];
const dirs: string[] = [];
const timers: Maintenance[] = [];
afterEach(() => {
  for (const m of timers.splice(0)) m.stop();
  for (const s of stores.splice(0)) s.close();
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

/**
 * `maxConcurrent` 0 holds every job in the queue, so a test can look at what was queued. Tests that need the
 * checks to actually run pass a larger number.
 */
function system(reconcile: Executor = async () => ({ detail: 'ok' }), intervalMs = 0, maxConcurrent = 0) {
  const store = new JobStore(':memory:');
  stores.push(store);
  const queue = new JobQueue({ store, maxConcurrent, executors: { reconcile } });
  const service = new JobService({
    store,
    queue,
    policy: { allowedRepoHosts: [], allowFileRepos: false },
    existsOnDisk: () => false,
  });
  const maintenance = new Maintenance({ store, service, intervalMs });
  timers.push(maintenance);
  const add = (project: string, opts: { bootstrapped?: boolean; org?: string } = {}) => {
    const org = opts.org ?? 'orgA';
    store.addProject({ orgId: org, projectId: project, repoUrl: 'https://github.com/a/b', branch: null, credentialsRef: null });
    if (opts.bootstrapped !== false) store.markBootstrapped(org, project);
  };
  return { store, queue, service, maintenance, add };
}

describe('Maintenance.tick', () => {
  it('queues a reconcile for every bootstrapped project, across orgs', () => {
    const { store, maintenance, add } = system();
    add('p1');
    add('p2');
    add('p1', { org: 'orgB' });
    expect(maintenance.tick()).toBe(3);
    const queued = store.queued().map((j) => `${j.orgId}/${j.projectId}:${j.type}`).sort();
    expect(queued).toEqual(['orgA/p1:reconcile', 'orgA/p2:reconcile', 'orgB/p1:reconcile']);
  });

  it('skips projects that are not bootstrapped, pruned, or already have a job', () => {
    const { store, maintenance, add } = system();
    add('fresh', { bootstrapped: false });
    add('pruned');
    store.markPruned('orgA', 'pruned');
    add('busy');
    store.create({ orgId: 'orgA', projectId: 'busy', type: 'sync', commitSha: 'a'.repeat(40) });
    add('free');

    expect(maintenance.tick()).toBe(1);
    expect(store.queued().filter((j) => j.type === 'reconcile').map((j) => j.projectId)).toEqual(['free']);
  });

  it('does not queue a second check while one is still active', async () => {
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    const { store, queue, maintenance, add } = system(async () => {
      await held;
    }, 0, 10);
    add('p1');
    expect(maintenance.tick()).toBe(1);
    expect(maintenance.tick()).toBe(0); // the first is running
    expect(store.activeForProject('orgA', 'p1')).toHaveLength(1);
    release();
    await queue.idle();
    expect(maintenance.tick()).toBe(1); // finished, so the next pass checks again
    await queue.idle();
  });

  it('keeps going when one project fails to queue', () => {
    const { store, service, maintenance, add } = system();
    add('p1');
    add('p2');
    const original = service.enqueueReconcile.bind(service);
    let calls = 0;
    service.enqueueReconcile = (org, project, key, hash) => {
      if (calls++ === 0) throw new Error('boom');
      return original(org, project, key, hash);
    };
    expect(maintenance.tick()).toBe(1);
    expect(store.queued().map((j) => j.projectId)).toEqual(['p2']);
  });

  it('start runs a pass at once and then on a schedule, and stop ends it', async () => {
    let runs = 0;
    const { queue, maintenance, add } = system(async () => {
      runs++;
      return { detail: 'ok' };
    }, 40, 10);
    add('p1');
    maintenance.start();
    expect(runs).toBe(1); // the immediate pass started a check at once
    await new Promise((r) => setTimeout(r, 300));
    await queue.idle();
    expect(runs).toBeGreaterThanOrEqual(3); // the immediate one, then the schedule kept going

    maintenance.stop();
    await queue.idle();
    const atStop = runs;
    await new Promise((r) => setTimeout(r, 200));
    await queue.idle();
    expect(runs).toBe(atStop); // nothing more after stop
  });

  it('with interval 0 runs one pass and no timer', async () => {
    let runs = 0;
    const { queue, maintenance, add } = system(async () => {
      runs++;
      return { detail: 'ok' };
    }, 0, 10);
    add('p1');
    maintenance.start();
    await queue.idle();
    await new Promise((r) => setTimeout(r, 150));
    await queue.idle();
    expect(runs).toBe(1); // the pass at startup, and no timer after it
    maintenance.stop();
  });
});

describe('index lag and disk in status', () => {
  const ready = (): ReadyProject => ({
    ready: true,
    dir: '/x',
    indexState: 'complete',
    lastIndexedAt: 1,
    cg: { getStats: () => ({ nodeCount: 1, edgeCount: 1, fileCount: 1, nodesByKind: { function: 1 } }) } as unknown as ReadyProject['cg'],
  });
  const NOW = 1_800_000_000_000;
  const A = 'a'.repeat(40);
  const B = 'b'.repeat(40);

  it('is null when the remote has never been checked', () => {
    expect(buildStatus(ready(), A, null, false, { binding: binding(), now: NOW }).index_lag_seconds).toBeNull();
    expect(buildStatus(ready(), A, null, false, { now: NOW }).index_lag_seconds).toBeNull();
  });

  it('is 0 when the index is at the remote head', () => {
    const s = buildStatus(ready(), A, null, false, { binding: binding({ remoteHead: A }), now: NOW });
    expect(s.index_lag_seconds).toBe(0);
  });

  it('counts the seconds since the index first fell behind', () => {
    const s = buildStatus(ready(), A, null, false, { binding: binding({ remoteHead: B, behindSince: NOW - 95_400 }), now: NOW });
    expect(s.index_lag_seconds).toBe(95);
  });

  it('never goes negative if the clock moved', () => {
    const s = buildStatus(ready(), A, null, false, { binding: binding({ remoteHead: B, behindSince: NOW + 5_000 }), now: NOW });
    expect(s.index_lag_seconds).toBe(0);
  });

  it('is 0, not an alarm, when the remote head is known but no lag clock is running', () => {
    expect(buildStatus(ready(), A, null, false, { binding: binding({ remoteHead: B }), now: NOW }).index_lag_seconds).toBe(0);
  });

  it('reports disk use only once measured', () => {
    expect(buildStatus(ready(), A, null, false, { binding: binding() }).disk).toBeNull();
    const measured = binding({ diskTreeBytes: 10, diskGitBytes: 20, diskIndexBytes: 30, diskMeasuredAt: Date.UTC(2026, 9, 28) });
    expect(buildStatus(ready(), A, null, false, { binding: measured }).disk).toEqual({
      tree_bytes: 10,
      git_bytes: 20,
      index_bytes: 30,
      measured_at: '2026-10-28T00:00:00.000Z',
    });
  });

  it('shows when a project was pruned', () => {
    const s = buildStatus({ ready: false, dir: '/x', reason: 'not_indexed', indexState: null }, null, null, false, {
      binding: binding({ prunedAt: Date.UTC(2026, 9, 1) }),
    });
    expect(s.pruned_at).toBe('2026-10-01T00:00:00.000Z');
    expect(s.state).toBe('not_indexed');
    expect(buildStatus(ready(), A, null, false, { binding: binding() }).pruned_at).toBeNull();
  });
});

describe('measureDisk', () => {
  it('splits a project into tree, git and index, and counts nested files', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-disk-'));
    dirs.push(dir);
    fs.mkdirSync(path.join(dir, '.git', 'objects'), { recursive: true });
    fs.mkdirSync(path.join(dir, '.codegraph'));
    fs.mkdirSync(path.join(dir, 'src', 'deep'), { recursive: true });
    fs.writeFileSync(path.join(dir, '.git', 'objects', 'pack'), Buffer.alloc(1000));
    fs.writeFileSync(path.join(dir, '.git', 'HEAD'), 'x'.repeat(10));
    fs.writeFileSync(path.join(dir, '.codegraph', 'codegraph.db'), Buffer.alloc(5000));
    fs.writeFileSync(path.join(dir, '.codegraph', 'codegraph.db-wal'), Buffer.alloc(300));
    fs.writeFileSync(path.join(dir, 'README.md'), 'x'.repeat(50));
    fs.writeFileSync(path.join(dir, 'src', 'a.ts'), 'x'.repeat(100));
    fs.writeFileSync(path.join(dir, 'src', 'deep', 'b.ts'), 'x'.repeat(200));
    expect(await measureDisk(dir)).toEqual({ tree: 350, git: 1010, index: 5300 });
  });

  it('reports zero for a folder that does not exist, and for an empty one', async () => {
    expect(await measureDisk(path.join(os.tmpdir(), 'astra-no-such-folder-xyz'))).toEqual({ tree: 0, git: 0, index: 0 });
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-disk-empty-'));
    dirs.push(dir);
    expect(await measureDisk(dir)).toEqual({ tree: 0, git: 0, index: 0 });
  });
});
