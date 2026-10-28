import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { runCodegraph } from '../src/jobs/codegraph-cli.js';
import { createExecutors } from '../src/jobs/executors.js';
import { createJobSystem, type JobSystem } from '../src/jobs/index.js';
import type { Executor, JobPhase } from '../src/jobs/types.js';
import { removeDir } from '../src/jobs/workspace.js';
import { ProjectRegistry } from '../src/projects.js';
import { buildServer } from '../src/server.js';
import { gitIn, makeOrigin, type Origin } from './git-helpers.js';
import { ORG_A_FILES, seedProject, signedEnvelope, testConfig } from './helpers.js';

// Sync against real git repositories and the real CodeGraph CLI: forward, rollback, rewritten history, repeats,
// failures, and what a caller sees while a sync is running.

const SLOW = 240_000;
let root: string;
let dataDir: string;
let origins: string;
let registry: ProjectRegistry;
let jobs: JobSystem;
let app: FastifyInstance;

/** What the test wants the CodeGraph CLI to do for the next `sync`. Undefined means run it for real. */
let cliOverride: undefined | ((args: readonly string[]) => Promise<Awaited<ReturnType<typeof runCodegraph>>>);
const phasesOfSyncs: JobPhase[][] = [];

const config = () => ({ ...testConfig(dataDir), allowFileRepos: true, bootstrapTimeoutMs: SLOW, syncTimeoutMs: SLOW });

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-sync-'));
  dataDir = path.join(root, 'data');
  origins = path.join(root, 'origins');
  fs.mkdirSync(dataDir);
  fs.mkdirSync(origins);

  const cfg = config();
  registry = new ProjectRegistry({ dataDir });
  jobs = createJobSystem(cfg, {
    storeFile: ':memory:',
    executors: (deps) => {
      const real = createExecutors(cfg, registry, deps, {
        runCodegraph: (args, run) => (cliOverride && args[0] === 'sync' ? cliOverride(args) : runCodegraph(args, run)),
      });
      const watchedSync: Executor = (ctx) => {
        const seen: JobPhase[] = [];
        phasesOfSyncs.push(seen);
        return real.sync!({ ...ctx, update: (p) => { if (p.phase) seen.push(p.phase); ctx.update(p); } });
      };
      return { ...real, sync: watchedSync };
    },
  });
  app = buildServer(cfg, { registry, jobs });
  await app.ready();
}, SLOW);

afterAll(async () => {
  await app.close();
  await removeDir(root);
});

const headers = (project: string, org = 'orgA') => ({ 'x-astra-envelope': signedEnvelope(org, project, ['project:admin', 'code:sync', 'query']) });
const post = (url: string, body: unknown, project: string, org = 'orgA') =>
  app.inject({ method: 'POST', url, headers: headers(project, org), payload: body as object });
const get = (url: string, project: string, org = 'orgA') => app.inject({ method: 'GET', url, headers: headers(project, org) });
const folder = (project: string, org = 'orgA') => path.join(dataDir, org, project);

async function run(project: string, body: object) {
  const res = await post('/internal/v1/code/jobs', body, project);
  expect(res.statusCode, res.body).toBe(202);
  await jobs.queue.idle();
  return (await get(`/internal/v1/code/jobs/${res.json().job_id}`, project)).json() as {
    state: string;
    error: string | null;
    commit_sha: string | null;
    counts?: { files: number; symbols: number; edges: number };
  };
}
const bootstrap = (project: string, origin: Origin) => run(project, { type: 'bootstrap', repo_url: origin.url });
const sync = (project: string, sha: string) => run(project, { type: 'sync', commit_sha: sha });
const status = async (project: string) => (await get('/internal/v1/code/status', project)).json();
const lookup = async (project: string, symbol: string) =>
  (await post('/internal/v1/code/query', { mode: 'lookup', symbols: [symbol] }, project)).json();
const found = (body: { results: Array<{ provenance: { symbol: string } }> }, name: string) =>
  body.results.some((r) => r.provenance.symbol === name);

describe('syncing forward, back, and across rewritten history', () => {
  let origin: Origin;
  let first: string;
  let second: string;

  beforeAll(async () => {
    origin = makeOrigin(origins, 'history', ORG_A_FILES);
    first = origin.head();
    const boot = await bootstrap('h', origin);
    expect(boot.state, boot.error ?? '').toBe('done');
    second = origin.commit({
      'web/extra.ts': 'export function brandNew() { return 7; }\n',
      'lib/token.ts': null, // a deleted file
    });
  }, SLOW);

  it('moves the checkout and the index to a newer commit, and the new symbols appear', async () => {
    expect(found(await lookup('h', 'brandNew'), 'brandNew')).toBe(false);
    expect(found(await lookup('h', 'issueToken'), 'issueToken')).toBe(true);

    const job = await sync('h', second);
    expect(job).toMatchObject({ state: 'done', error: null, commit_sha: second });
    expect(job.counts?.files).toBe(3); // app.ts, index.ts and extra.ts; token.ts is gone

    expect(gitIn(folder('h'), 'rev-parse', 'HEAD')).toBe(second);
    expect(found(await lookup('h', 'brandNew'), 'brandNew')).toBe(true);
    expect(found(await lookup('h', 'issueToken'), 'issueToken')).toBe(false); // deleted in the new commit
    expect((await status('h')).last_synced_sha).toBe(second);
    expect(gitIn(folder('h'), 'status', '--porcelain')).toBe('?? .codegraph/'); // never cleaned
  }, SLOW);

  it('reports the commit in citations after the sync', async () => {
    const res = await post('/internal/v1/code/query', { mode: 'lookup', symbols: ['brandNew'] }, 'h');
    expect(res.json().snapshot.commit_sha).toBe(second);
    expect(res.json().results[0].citation).toMatch(new RegExp(`@${second.slice(0, 7)}\\)$`));
    expect(res.json().results[0].text).toContain('return 7');
  });

  it('rolls back to an older commit: files restored, new symbols gone', async () => {
    const job = await sync('h', first);
    expect(job).toMatchObject({ state: 'done', commit_sha: first });
    expect(gitIn(folder('h'), 'rev-parse', 'HEAD')).toBe(first);
    expect(found(await lookup('h', 'brandNew'), 'brandNew')).toBe(false);
    expect(found(await lookup('h', 'issueToken'), 'issueToken')).toBe(true); // restored
    expect((await status('h')).last_synced_sha).toBe(first);
  }, SLOW);

  it('follows a commit that is not a descendant of what was indexed (rewritten history)', async () => {
    origin.branch('rewritten', first);
    const rewritten = origin.commit({ 'web/rewrite.ts': 'export function afterRewrite() { return 9; }\n' });
    const job = await sync('h', rewritten);
    expect(job, job.error ?? '').toMatchObject({ state: 'done' });
    expect(gitIn(folder('h'), 'rev-parse', 'HEAD')).toBe(rewritten);
    expect(found(await lookup('h', 'afterRewrite'), 'afterRewrite')).toBe(true);
    expect((await status('h')).last_synced_sha).toBe(rewritten);
  }, SLOW);

  it('does nothing for a commit the index already reflects, and says so in a few seconds', async () => {
    const current = (await status('h')).last_synced_sha as string;
    phasesOfSyncs.length = 0;
    const started = Date.now();
    const job = await sync('h', current);
    expect(job.state).toBe('done');
    expect(Date.now() - started).toBeLessThan(15_000);
    // It never reached the scanning or parsing phases: no fetch and no indexing happened.
    expect(phasesOfSyncs.flat()).toEqual(['finalizing']);
    expect((await status('h')).last_synced_sha).toBe(current);
  }, SLOW);
});

describe('a sync that fails leaves the project usable', () => {
  let origin: Origin;
  let first: string;

  beforeAll(async () => {
    origin = makeOrigin(origins, 'failing', ORG_A_FILES);
    first = origin.head();
    expect((await bootstrap('f', origin)).state).toBe('done');
  }, SLOW);

  it('fails cleanly on a commit the remote does not have, and changes nothing', async () => {
    const job = await sync('f', 'e'.repeat(40));
    expect(job.state).toBe('failed');
    expect(job.error).toContain('git fetch failed');
    expect(gitIn(folder('f'), 'rev-parse', 'HEAD')).toBe(first);
    const s = await status('f');
    expect(s).toMatchObject({ state: 'ready', last_synced_sha: first });
    expect(found(await lookup('f', 'render'), 'render')).toBe(true);
  }, SLOW);

  it('moves the checkout back when indexing fails after it moved, so files and index agree', async () => {
    const second = origin.commit({ 'web/new.ts': 'export function neverIndexed() { return 1; }\n' });
    cliOverride = async () => ({ code: 3, stdout: '', stderr: 'simulated indexer crash', timedOut: false, aborted: false });
    try {
      const job = await sync('f', second);
      expect(job.state).toBe('failed');
      expect(job.error).toContain('codegraph sync failed (exit 3)');
      expect(job.error).toContain('moved back to');
    } finally {
      cliOverride = undefined;
    }
    expect(gitIn(folder('f'), 'rev-parse', 'HEAD')).toBe(first); // back where the index is
    expect(fs.existsSync(path.join(folder('f'), 'web', 'new.ts'))).toBe(false);
    expect((await status('f')).last_synced_sha).toBe(first);
    expect(found(await lookup('f', 'neverIndexed'), 'neverIndexed')).toBe(false);

    // The next sync works.
    const retry = await sync('f', second);
    expect(retry, retry.error ?? '').toMatchObject({ state: 'done' });
    expect(found(await lookup('f', 'neverIndexed'), 'neverIndexed')).toBe(true);
  }, SLOW);
});

describe('what a caller sees while a sync is running', () => {
  it('keeps answering, but flags that files and index may disagree', async () => {
    const origin = makeOrigin(origins, 'busy', ORG_A_FILES);
    expect((await bootstrap('busy', origin)).state).toBe('done');
    const next = origin.commit({ 'web/later.ts': 'export function later() { return 2; }\n' });

    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    let reached!: () => void;
    const atIndexing = new Promise<void>((res) => (reached = res));
    cliOverride = async () => {
      reached();
      await held;
      return { code: 0, stdout: '', stderr: '', timedOut: false, aborted: false };
    };

    const submitted = await post('/internal/v1/code/jobs', { type: 'sync', commit_sha: next }, 'busy');
    await atIndexing; // the tree has moved; the index has not

    const query = await post('/internal/v1/code/query', { mode: 'callers', symbols: ['render'] }, 'busy');
    expect(query.statusCode).toBe(200);
    expect(query.json().results.length).toBeGreaterThan(0);
    expect(query.json().snapshot.sync_in_progress).toBe(true);
    expect(query.json().plane_status).toBe('degraded');

    const during = await status('busy');
    expect(during).toMatchObject({ state: 'ready', active_job: submitted.json().job_id, snapshot: { sync_in_progress: true } });

    cliOverride = undefined;
    release();
    await jobs.queue.idle();
    // The held CLI "succeeded" without indexing, so the sync is rejected by the stamp check, and the tree goes back.
    const after = await status('busy');
    expect(after.snapshot.sync_in_progress).toBe(false);
    expect(after.active_job).toBeNull();
    const job = (await get(`/internal/v1/code/jobs/${submitted.json().job_id}`, 'busy')).json();
    expect(job.state).toBe('failed');
    expect(job.error).toContain('index reports commit');
    const settled = await post('/internal/v1/code/query', { mode: 'callers', symbols: ['render'] }, 'busy');
    expect(settled.json().plane_status).toBe('ok');
    expect(settled.json().snapshot.sync_in_progress).toBe(false);
  }, SLOW);

  it('shows a project as indexing while its first bootstrap runs', async () => {
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    const cfg = config();
    const reg = new ProjectRegistry({ dataDir });
    const system = createJobSystem(cfg, {
      storeFile: ':memory:',
      executors: {
        bootstrap: async () => {
          await held;
        },
      },
    });
    const slowApp = buildServer(cfg, { registry: reg, jobs: system });
    await slowApp.ready();
    const h = headers('booting');
    const res = await slowApp.inject({ method: 'POST', url: '/internal/v1/code/jobs', headers: h, payload: { type: 'bootstrap', repo_url: 'https://github.com/acme/app' } });
    const s = (await slowApp.inject({ method: 'GET', url: '/internal/v1/code/status', headers: h })).json();
    expect(s).toMatchObject({ state: 'indexing', active_job: res.json().job_id, snapshot: { index_state: 'not_indexed', sync_in_progress: true } });
    const q = (await slowApp.inject({ method: 'POST', url: '/internal/v1/code/query', headers: h, payload: { mode: 'lookup', keywords: ['x'] } })).json();
    expect(q).toMatchObject({ plane_status: 'not_ready', results: [] });
    release();
    await system.queue.idle();
    await slowApp.close();
  }, SLOW);
});

describe('a later commit that adds a symlink', () => {
  it('turns it into a plain file on sync, so it cannot reach another tenant', async () => {
    await seedProject(dataDir, 'orgB', 'p1', { 'secret.ts': 'export function victimSecretFn() { return "ORG-B-PRIVATE"; }\n' });
    const origin = makeOrigin(origins, 'later-evil', { 'src/ok.ts': 'export function legit() { return 1; }\n' });
    expect((await bootstrap('evil2', origin)).state).toBe('done');
    const evil = origin.commitSymlink('src/leak.ts', '../../../orgB/p1/secret.ts');

    const job = await sync('evil2', evil);
    expect(job, job.error ?? '').toMatchObject({ state: 'done' });
    const leak = path.join(folder('evil2'), 'src', 'leak.ts');
    expect(fs.lstatSync(leak).isSymbolicLink()).toBe(false);
    expect(found(await lookup('evil2', 'victimSecretFn'), 'victimSecretFn')).toBe(false);
    expect(found(await lookup('evil2', 'legit'), 'legit')).toBe(true);
  }, SLOW);
});
