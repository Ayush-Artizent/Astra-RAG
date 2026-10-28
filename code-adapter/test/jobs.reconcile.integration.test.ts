import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { databasePath } from '../src/codegraph.js';
import { runCodegraph } from '../src/jobs/codegraph-cli.js';
import { createExecutors, createRecoveryFor } from '../src/jobs/executors.js';
import { createJobSystem, type JobSystem } from '../src/jobs/index.js';
import { readIndexedCommit } from '../src/jobs/stamp.js';
import { removeDir } from '../src/jobs/workspace.js';
import { ProjectRegistry } from '../src/projects.js';
import { buildServer } from '../src/server.js';
import { DatabaseSync } from '../src/sqlite.js';
import { gitIn, makeOrigin, type Origin } from './git-helpers.js';
import { ORG_A_FILES, signedEnvelope, testConfig } from './helpers.js';

// Reconcile against real git repositories and the real indexer: staying in step with the remote, healing damage,
// housekeeping, and pruning.

const SLOW = 300_000;
const DAY = 86_400_000;
let root: string;
let dataDir: string;
let origins: string;
let registry: ProjectRegistry;
let jobs: JobSystem;
let app: FastifyInstance;
/** A hook to hold the next `codegraph sync` at a chosen moment. */
let syncGate: undefined | (() => Promise<void>);

// The executors read these at run time, so a test can change them.
const cfg = { ...testConfig(''), allowFileRepos: true, bootstrapTimeoutMs: SLOW, syncTimeoutMs: SLOW };

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-reconcile-'));
  dataDir = path.join(root, 'data');
  origins = path.join(root, 'origins');
  fs.mkdirSync(dataDir);
  fs.mkdirSync(origins);
  cfg.dataDir = dataDir;

  registry = new ProjectRegistry({ dataDir });
  jobs = createJobSystem(cfg, {
    storeFile: ':memory:',
    executors: (deps) =>
      createExecutors(cfg, registry, deps, {
        runCodegraph: async (args, run) => {
          if (args[0] === 'sync' && syncGate) await syncGate();
          return runCodegraph(args, run);
        },
      }),
  });
  app = buildServer(cfg, { registry, jobs });
  await app.ready();
}, SLOW);

afterAll(async () => {
  await app.close();
  await removeDir(root);
});

const headers = (project: string, org = 'orgA') => ({ 'x-astra-envelope': signedEnvelope(org, project, ['project:admin', 'code:sync', 'query']) });
const post = (url: string, body: unknown, project: string) => app.inject({ method: 'POST', url, headers: headers(project), payload: body as object });
const get = (url: string, project: string) => app.inject({ method: 'GET', url, headers: headers(project) });
const folder = (project: string) => path.join(dataDir, 'orgA', project);
const status = async (project: string) => (await get('/internal/v1/code/status', project)).json();
const lookup = async (project: string, symbol: string) => (await post('/internal/v1/code/query', { mode: 'lookup', symbols: [symbol] }, project)).json();
const found = (body: { results: Array<{ provenance: { symbol: string } }> }, name: string) => body.results.some((r) => r.provenance.symbol === name);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

type JobBody = { state: string; type: string; detail: string | null; error: string | null };
async function waitForJob(id: string, project: string): Promise<JobBody> {
  const end = Date.now() + SLOW;
  for (;;) {
    const job = (await get(`/internal/v1/code/jobs/${id}`, project)).json() as JobBody;
    if (['done', 'failed', 'superseded'].includes(job.state)) return job;
    if (Date.now() > end) throw new Error(`job ${id} did not finish`);
    await sleep(150);
  }
}

async function bootstrap(project: string, origin: Origin) {
  const res = await post('/internal/v1/code/jobs', { type: 'bootstrap', repo_url: origin.url }, project);
  expect(res.statusCode, res.body).toBe(202);
  await jobs.queue.idle();
  expect((await status(project)).state, project).toBe('ready');
}
const reconcileRequest = (project: string) => post('/internal/v1/code/jobs', { type: 'reconcile' }, project);
async function reconcile(project: string) {
  const res = await reconcileRequest(project);
  expect(res.statusCode, res.body).toBe(202);
  await jobs.queue.idle();
  return (await get(`/internal/v1/code/jobs/${res.json().job_id}`, project)).json() as JobBody;
}
const jobsOf = (project: string) => jobs.store.recentJobs('orgA', project).map((j) => `${j.type}:${j.state}`);

describe('staying in step with the remote', () => {
  it('reports an up-to-date project, with lag 0 and its disk use', async () => {
    const origin = makeOrigin(origins, 'uptodate', ORG_A_FILES);
    await bootstrap('u', origin);
    expect((await status('u')).index_lag_seconds).toBeNull(); // never checked yet

    const job = await reconcile('u');
    expect(job).toMatchObject({ type: 'reconcile', state: 'done', error: null });
    expect(job.detail).toBe(`up to date at ${origin.head().slice(0, 7)}`);

    const s = await status('u');
    expect(s.index_lag_seconds).toBe(0);
    expect(s.disk.tree_bytes).toBeGreaterThan(100);
    expect(s.disk.git_bytes).toBeGreaterThan(1000);
    expect(s.disk.index_bytes).toBeGreaterThan(10_000);
    expect(Date.parse(s.disk.measured_at)).not.toBeNaN();
    expect(jobs.store.getProject('orgA', 'u')?.remoteHead).toBe(origin.head());
    expect(jobsOf('u')).toEqual(['reconcile:done', 'bootstrap:done']); // nothing else was queued
  }, SLOW);

  it('catches a push whose webhook was missed: queues the sync itself, and the lag clock runs until it finishes', async () => {
    const origin = makeOrigin(origins, 'missed', ORG_A_FILES);
    await bootstrap('m', origin);
    const indexed = origin.head(); // what the index reflects, before the push
    const newer = origin.commit({ 'web/pushed.ts': 'export function pushedLater() { return 1; }\n' });
    expect(found(await lookup('m', 'pushedLater'), 'pushedLater')).toBe(false);

    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    let reachedSync!: () => void;
    const atSync = new Promise<void>((res) => (reachedSync = res));
    syncGate = async () => {
      reachedSync();
      await held;
    };
    try {
      const res = await reconcileRequest('m');
      await atSync; // the reconcile found the index behind and its sync has started
      const job = await waitForJob(res.json().job_id, 'm');
      expect(job.state).toBe('done');
      expect(job.detail).toMatch(new RegExp(`^behind: the remote is at ${newer.slice(0, 7)} and the index at ${indexed.slice(0, 7)}; queued sync job_`));

      await sleep(1_300);
      const during = await status('m');
      expect(during.index_lag_seconds).toBeGreaterThanOrEqual(1);
      expect(during.snapshot.sync_in_progress).toBe(true);
      expect(during.last_synced_sha).not.toBe(newer);
    } finally {
      syncGate = undefined;
      release();
    }
    await jobs.queue.idle();

    const after = await status('m');
    expect(after.last_synced_sha).toBe(newer);
    expect(after.index_lag_seconds).toBe(0);
    expect(found(await lookup('m', 'pushedLater'), 'pushedLater')).toBe(true);
  }, SLOW);

  it('starts the lag clock when a webhook asks for a sync, and stops it when that sync lands', async () => {
    const origin = makeOrigin(origins, 'webhook', ORG_A_FILES);
    await bootstrap('w', origin);
    expect((await status('w')).index_lag_seconds).toBeNull();
    const pushed = origin.commit({ 'web/hook.ts': 'export function hooked() { return 1; }\n' });

    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    let reached!: () => void;
    const atSync = new Promise<void>((res) => (reached = res));
    syncGate = async () => {
      reached();
      await held;
    };
    try {
      await post('/internal/v1/code/jobs', { type: 'sync', commit_sha: pushed }, 'w');
      await atSync;
      await sleep(1_300);
      expect((await status('w')).index_lag_seconds).toBeGreaterThanOrEqual(1);
    } finally {
      syncGate = undefined;
      release();
    }
    await jobs.queue.idle();
    expect((await status('w')).index_lag_seconds).toBe(0);
  }, SLOW);

  it('moves the files back first when a cut-off sync left them ahead of the index, then catches up', async () => {
    const origin = makeOrigin(origins, 'ahead', ORG_A_FILES);
    const indexed = origin.head();
    await bootstrap('a', origin);
    const next = origin.commit({ 'web/ahead.ts': 'export function aheadFn() { return 1; }\n' });
    registry.evict('orgA', 'a');
    gitIn(folder('a'), '-c', 'protocol.file.allow=always', 'fetch', '--depth', '1', 'origin', next);
    gitIn(folder('a'), 'reset', '--hard', '--quiet', next);
    expect(readIndexedCommit(folder('a'))).toBe(indexed); // files at `next`, index at `indexed`

    const job = await reconcile('a');
    expect(job.detail).toContain(`moved the files back to ${indexed.slice(0, 7)}`);
    expect(job.detail).toContain('behind:');
    expect(gitIn(folder('a'), 'rev-parse', 'HEAD')).toBe(next); // and the queued sync brought both forward
    expect(readIndexedCommit(folder('a'))).toBe(next);
    expect(found(await lookup('a', 'aheadFn'), 'aheadFn')).toBe(true);
  }, SLOW);
});

describe('healing a damaged project', () => {
  async function expectRebuilt(project: string, origin: Origin, why: RegExp) {
    const job = await reconcile(project);
    expect(job.state).toBe('done');
    expect(job.detail).toMatch(why);
    expect(jobsOf(project)[0]).toBe('bootstrap:done'); // the queued rebuild ran and finished
    const s = await status(project);
    expect(s).toMatchObject({ state: 'ready', last_synced_sha: origin.head() });
    expect(found(await lookup(project, 'render'), 'render')).toBe(true);
    expect(gitIn(folder(project), 'status', '--porcelain')).toBe('?? .codegraph/');
  }

  it('rebuilds a project whose index file is damaged', async () => {
    const origin = makeOrigin(origins, 'damaged', ORG_A_FILES);
    await bootstrap('d', origin);
    registry.evict('orgA', 'd');
    fs.writeFileSync(databasePath(folder('d')), Buffer.from('not a database at all '.repeat(400)));
    await expectRebuilt('d', origin, /^queued a rebuild, because the index file is damaged$/);
  }, SLOW);

  it('rebuilds a project whose folder is gone', async () => {
    const origin = makeOrigin(origins, 'gone', ORG_A_FILES);
    await bootstrap('g', origin);
    registry.evict('orgA', 'g');
    await removeDir(folder('g'));
    expect((await status('g')).state).toBe('not_indexed');
    await expectRebuilt('g', origin, /^queued a rebuild, because the project folder is missing$/);
  }, SLOW);

  it('rebuilds a project whose index was left marked as failed', async () => {
    const origin = makeOrigin(origins, 'failedidx', ORG_A_FILES);
    await bootstrap('f', origin);
    registry.evict('orgA', 'f');
    const db = new DatabaseSync(databasePath(folder('f')));
    db.prepare("UPDATE project_metadata SET value = 'failed' WHERE key = 'index_state'").run();
    db.close();
    await expectRebuilt('f', origin, /^queued a rebuild, because the index is marked failed$/);
  }, SLOW);

  it('keeps the project when a rebuild fails, and heals on a later check once the remote is back', async () => {
    const origin = makeOrigin(origins, 'flaky', ORG_A_FILES);
    await bootstrap('r', origin);
    registry.evict('orgA', 'r');
    await removeDir(folder('r'));
    fs.renameSync(origin.dir, `${origin.dir}-away`); // the remote is unreachable

    const first = await reconcile('r');
    expect(first.detail).toMatch(/^queued a rebuild/);
    expect(jobsOf('r')[0]).toBe('bootstrap:failed'); // the rebuild could not clone
    expect(jobs.store.getProject('orgA', 'r')?.bootstrappedAt).not.toBeNull(); // the repo record survived
    expect(fs.existsSync(folder('r'))).toBe(false); // and no half-made folder
    expect((await status('r')).state).toBe('not_indexed');

    fs.renameSync(`${origin.dir}-away`, origin.dir); // the remote comes back
    const second = await reconcile('r');
    expect(second.detail).toMatch(/^queued a rebuild/);
    expect(jobsOf('r')[0]).toBe('bootstrap:done');
    expect((await status('r'))).toMatchObject({ state: 'ready', last_synced_sha: origin.head() });
  }, SLOW);
});

describe('housekeeping', () => {
  it('runs git gc when loose objects pile up, without touching the files or the index', async () => {
    const origin = makeOrigin(origins, 'garbage', ORG_A_FILES);
    await bootstrap('c', origin);
    for (let i = 0; i < 2; i++) {
      const sha = origin.commit({ [`web/big${i}.ts`]: `export const data${i} = "${'x'.repeat(8000)}";\n` });
      await post('/internal/v1/code/jobs', { type: 'sync', commit_sha: sha }, 'c');
      await jobs.queue.idle();
    }
    const gitBefore = (await status('c')).disk.git_bytes;
    const headBefore = gitIn(folder('c'), 'rev-parse', 'HEAD');
    const indexBefore = (await status('c')).disk.index_bytes;

    const saved = cfg.gcLooseObjects;
    cfg.gcLooseObjects = 1;
    try {
      const job = await reconcile('c');
      expect(job.detail).toMatch(/ran git gc \(loose objects (\d+) \(\d+ KB\) -> (\d+) \(\d+ KB\)\)/);
      const [, before, after] = /loose objects (\d+) \(\d+ KB\) -> (\d+)/.exec(job.detail ?? '') ?? [];
      expect(Number(before)).toBeGreaterThan(0);
      expect(Number(after)).toBeLessThan(Number(before));
    } finally {
      cfg.gcLooseObjects = saved;
    }

    const after = await status('c');
    expect(after.disk.git_bytes).toBeLessThan(gitBefore); // the old commits' objects are gone
    expect(after.disk.index_bytes).toBeGreaterThanOrEqual(indexBefore * 0.9); // the index is untouched
    expect(gitIn(folder('c'), 'rev-parse', 'HEAD')).toBe(headBefore);
    expect(gitIn(folder('c'), 'status', '--porcelain')).toBe('?? .codegraph/');
    expect(after.state).toBe('ready');
    expect(found(await lookup('c', 'render'), 'render')).toBe(true);
  }, SLOW);

  it('does not run git gc below the threshold', async () => {
    const origin = makeOrigin(origins, 'tidy', ORG_A_FILES);
    await bootstrap('t', origin);
    const job = await reconcile('t');
    expect(job.detail).not.toContain('git gc');
  }, SLOW);
});

describe('idle pruning', () => {
  it('never deletes anything while the idle period is 0, however old the project is', async () => {
    const origin = makeOrigin(origins, 'neverprune', ORG_A_FILES);
    await bootstrap('n', origin);
    jobs.store.touchProject('orgA', 'n', Date.now() - 400 * DAY);
    expect(cfg.idleProjectDays).toBe(0);
    const job = await reconcile('n');
    expect(job.detail).toMatch(/^up to date/);
    expect(fs.existsSync(folder('n'))).toBe(true);
  }, SLOW);

  it('deletes an idle project, and a query rebuilds it on demand', async () => {
    const origin = makeOrigin(origins, 'prune', ORG_A_FILES);
    await bootstrap('i', origin);
    jobs.store.touchProject('orgA', 'i', Date.now() - 3 * DAY);

    cfg.idleProjectDays = 2;
    try {
      const job = await reconcile('i');
      expect(job.detail).toMatch(/^pruned: not queried for more than 2 days/);
    } finally {
      cfg.idleProjectDays = 0;
    }
    expect(fs.existsSync(folder('i'))).toBe(false);
    const gone = await status('i');
    expect(gone).toMatchObject({ state: 'not_indexed', disk: null });
    expect(Date.parse(gone.pruned_at)).not.toBeNaN();

    // (The schedule skipping a pruned project is covered by the Maintenance unit tests.)

    // A query gets `not_ready` and starts the rebuild.
    const first = await post('/internal/v1/code/query', { mode: 'lookup', symbols: ['render'] }, 'i');
    expect(first.json()).toMatchObject({ plane_status: 'not_ready', results: [] });
    expect((await status('i')).state).toBe('indexing'); // a rebuild is queued or running
    await jobs.queue.idle();

    const rebuilt = await status('i');
    expect(rebuilt).toMatchObject({ state: 'ready', pruned_at: null, last_synced_sha: origin.head() });
    expect(found(await lookup('i', 'render'), 'render')).toBe(true);
    expect(jobsOf('i').slice(0, 2)).toEqual(['bootstrap:done', 'reconcile:done']);
  }, SLOW);

  it('does not prune a project that was queried recently', async () => {
    const origin = makeOrigin(origins, 'recent', ORG_A_FILES);
    await bootstrap('e', origin);
    jobs.store.touchProject('orgA', 'e', Date.now() - 1 * DAY);
    cfg.idleProjectDays = 2;
    try {
      expect((await reconcile('e')).detail).toMatch(/^up to date/);
    } finally {
      cfg.idleProjectDays = 0;
    }
    expect(fs.existsSync(folder('e'))).toBe(true);
  }, SLOW);

  it('counts a query as use, so a queried project is not pruned', async () => {
    const origin = makeOrigin(origins, 'queried', ORG_A_FILES);
    await bootstrap('q', origin);
    jobs.store.touchProject('orgA', 'q', Date.now() - 10 * DAY);
    await lookup('q', 'render'); // a query records the use
    expect(Date.now() - (jobs.store.getProject('orgA', 'q')?.lastUsedAt ?? 0)).toBeLessThan(60_000);
    cfg.idleProjectDays = 2;
    try {
      expect((await reconcile('q')).detail).toMatch(/^up to date/);
    } finally {
      cfg.idleProjectDays = 0;
    }
  }, SLOW);
});

describe('the schedule', () => {
  it('checks every project once at startup', async () => {
    const storeFile = path.join(root, 'startup.db');
    const origin = makeOrigin(origins, 'startup', ORG_A_FILES);
    const build = async () => {
      const reg = new ProjectRegistry({ dataDir });
      const system = createJobSystem(cfg, {
        storeFile,
        executors: (deps) => createExecutors(cfg, reg, deps),
        recover: createRecoveryFor(cfg, reg),
      });
      const server = buildServer(cfg, { registry: reg, jobs: system });
      await server.ready();
      return { server, system };
    };

    const first = await build();
    const res = await first.server.inject({ method: 'POST', url: '/internal/v1/code/jobs', headers: headers('boot'), payload: { type: 'bootstrap', repo_url: origin.url } });
    expect(res.statusCode).toBe(202);
    await first.system.queue.idle();
    const countBefore = first.system.store.recentJobs('orgA', 'boot').filter((j) => j.type === 'reconcile').length;
    await first.server.close();

    // A new process: the startup pass queues a reconcile for the project it finds in the job file.
    const second = await build();
    await second.system.queue.idle();
    const reconciles = second.system.store.recentJobs('orgA', 'boot').filter((j) => j.type === 'reconcile');
    expect(reconciles.length).toBe(countBefore + 1);
    expect(reconciles[0]).toMatchObject({ state: 'done' });
    expect(reconciles[0]?.detail).toMatch(/^up to date/);
    await second.server.close();
  }, SLOW);
});
