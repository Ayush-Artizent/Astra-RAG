import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createJobSystem, type JobSystem } from '../src/jobs/index.js';
import type { Executor } from '../src/jobs/types.js';
import { buildServer } from '../src/server.js';
import { signedEnvelope, testConfig } from './helpers.js';

const REPO = 'https://github.com/acme/app';
const sha = (c: string) => c.repeat(40);

let dataDir: string;
let app: FastifyInstance;
let jobs: JobSystem;
/** Replaceable per test. */
let bootstrapImpl: Executor;
let syncImpl: Executor;
let reconcileImpl: Executor;

beforeEach(async () => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-jobs-'));
  bootstrapImpl = async () => ({ files: 10, symbols: 100, edges: 300 });
  syncImpl = async () => ({ files: 10, symbols: 101, edges: 301 });
  reconcileImpl = async () => ({ detail: 'up to date' });
  const config = testConfig(dataDir);
  jobs = createJobSystem(config, {
    storeFile: ':memory:',
    executors: { bootstrap: (ctx) => bootstrapImpl(ctx), sync: (ctx) => syncImpl(ctx), reconcile: (ctx) => reconcileImpl(ctx) },
  });
  app = buildServer(config, { jobs });
  await app.ready();
});

afterEach(async () => {
  await app.close();
  fs.rmSync(dataDir, { recursive: true, force: true });
});

interface Opts {
  org?: string;
  project?: string;
  scopes?: string[];
  key?: string;
}

const headers = (o: Opts) => ({
  'x-astra-envelope': signedEnvelope(o.org ?? 'orgA', o.project ?? 'p1', o.scopes ?? ['project:admin', 'code:sync', 'query']),
  ...(o.key !== undefined ? { 'idempotency-key': o.key } : {}),
});
const submit = (body: unknown, o: Opts = {}) =>
  app.inject({ method: 'POST', url: '/internal/v1/code/jobs', headers: headers(o), payload: body as object });
const getJob = (id: string, o: Opts = {}) =>
  app.inject({ method: 'GET', url: `/internal/v1/code/jobs/${id}`, headers: headers(o) });

const bootstrap = (o: Opts = {}, extra: object = {}) => submit({ type: 'bootstrap', repo_url: REPO, ...extra }, o);
const syncTo = (c: string, o: Opts = {}) => submit({ type: 'sync', commit_sha: sha(c) }, o);

async function bootstrapAndWait(o: Opts = {}) {
  const res = await bootstrap(o);
  expect(res.statusCode).toBe(202);
  await jobs.queue.idle();
  return res.json().job_id as string;
}

const tick = () => new Promise((r) => setImmediate(r));

describe('bootstrap', () => {
  it('is accepted with 202, runs, and reports counts', async () => {
    const res = await bootstrap();
    expect(res.statusCode).toBe(202);
    const body = res.json();
    expect(body.job_id).toMatch(/^job_[0-9a-f]{32}$/);
    expect(body.status_url).toBe(`/internal/v1/code/jobs/${body.job_id}`);
    expect(['queued', 'running']).toContain(body.state);

    await jobs.queue.idle();
    const job = (await getJob(body.job_id)).json();
    expect(job).toMatchObject({ job_id: body.job_id, type: 'bootstrap', state: 'done', progress: 1, error: null, counts: { files: 10, symbols: 100, edges: 300 } });
    expect(Date.parse(job.created_at)).not.toBeNaN();
    expect(Date.parse(job.finished_at)).not.toBeNaN();
  });

  it('needs the project:admin scope, and sync does not satisfy it', async () => {
    const res = await bootstrap({ scopes: ['code:sync', 'query'] });
    expect(res.statusCode).toBe(403);
    expect(res.json().error_code).toBe('scope_missing');
    expect(jobs.store.queued()).toEqual([]);
    expect(jobs.store.getProject('orgA', 'p1')).toBeUndefined();
  });

  it('stores the repo binding with the credential name only', async () => {
    await bootstrap({}, { credentials_ref: 'acme-prod', branch: 'main' });
    const binding = jobs.store.getProject('orgA', 'p1');
    expect(binding).toMatchObject({ repoUrl: REPO, branch: 'main', credentialsRef: 'acme-prod' });
    await jobs.queue.idle();
  });

  it('is refused while one is running, and after it finished', async () => {
    const release = (() => {
      let r!: () => void;
      const p = new Promise<void>((res) => (r = res));
      bootstrapImpl = async () => {
        await p;
      };
      return r;
    })();
    const first = await bootstrap();
    expect(first.statusCode).toBe(202);

    const during = await bootstrap();
    expect(during.statusCode).toBe(409);
    expect(during.json().error_code).toBe('job_conflict');

    release();
    await jobs.queue.idle();
    const after = await bootstrap();
    expect(after.statusCode).toBe(409);
    expect(after.json().error_code).toBe('job_conflict');
  });

  it('can be retried after a failure, which leaves no binding behind', async () => {
    bootstrapImpl = async () => {
      throw new Error('fatal: repository not found');
    };
    const id = await bootstrapAndWait();
    expect((await getJob(id)).json()).toMatchObject({ state: 'failed', error: 'fatal: repository not found' });
    expect(jobs.store.getProject('orgA', 'p1')).toBeUndefined();

    bootstrapImpl = async () => ({ files: 1 });
    const retry = await bootstrap();
    expect(retry.statusCode).toBe(202);
    await jobs.queue.idle();
    expect(jobs.store.getProject('orgA', 'p1')?.bootstrappedAt).not.toBeNull();
  });

  it('is refused when something already exists on disk for the project', async () => {
    fs.mkdirSync(path.join(dataDir, 'orgA', 'p1'), { recursive: true });
    const res = await bootstrap();
    expect(res.statusCode).toBe(409);
    expect(res.json().error_code).toBe('job_conflict');
    expect(jobs.store.getProject('orgA', 'p1')).toBeUndefined();
  });

  it('works independently in two orgs that share a project id', async () => {
    await bootstrapAndWait({ org: 'orgA' });
    const b = await bootstrap({ org: 'orgB' });
    expect(b.statusCode).toBe(202);
    await jobs.queue.idle();
    expect(jobs.store.getProject('orgA', 'p1')).toBeDefined();
    expect(jobs.store.getProject('orgB', 'p1')).toBeDefined();
  });

  it.each([
    ['http, not https', { repo_url: 'http://github.com/a/b' }, 'repo_url'],
    ['loopback', { repo_url: 'https://127.0.0.1/a/b' }, 'repo_url'],
    ['cloud metadata address', { repo_url: 'https://169.254.169.254/latest' }, 'repo_url'],
    ['file url', { repo_url: 'file:///etc' }, 'repo_url'],
    ['credentials in the url', { repo_url: 'https://u:p@github.com/a/b' }, 'repo_url'],
    ['option-like branch', { branch: '--upload-pack=evil' }, 'branch'],
    ['bad credentials_ref', { credentials_ref: 'a b' }, 'credentials_ref'],
  ])('rejects %s with 422 naming the field', async (_name, extra, field) => {
    const res = await submit({ type: 'bootstrap', repo_url: REPO, ...extra });
    expect(res.statusCode).toBe(422);
    expect(res.json()).toMatchObject({ error_code: 'invalid_field', field });
    expect(jobs.store.getProject('orgA', 'p1')).toBeUndefined();
  });
});

describe('sync', () => {
  it('is refused before the project is bootstrapped, and while its bootstrap is still running', async () => {
    const before = await syncTo('a');
    expect(before.statusCode).toBe(409);
    expect(before.json().error_code).toBe('job_conflict');

    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    bootstrapImpl = async () => {
      await held;
    };
    await bootstrap();
    const during = await syncTo('a');
    expect(during.statusCode).toBe(409);

    release();
    await jobs.queue.idle();
    expect((await syncTo('a')).statusCode).toBe(202);
    await jobs.queue.idle();
  });

  it('needs the code:sync scope, and project:admin does not satisfy it', async () => {
    await bootstrapAndWait();
    const res = await syncTo('a', { scopes: ['project:admin', 'query'] });
    expect(res.statusCode).toBe(403);
    expect(res.json().error_code).toBe('scope_missing');
  });

  it('runs and reports its commit', async () => {
    await bootstrapAndWait();
    const res = await syncTo('b');
    expect(res.statusCode).toBe(202);
    await jobs.queue.idle();
    expect((await getJob(res.json().job_id)).json()).toMatchObject({ type: 'sync', state: 'done', commit_sha: sha('b'), counts: { files: 10, symbols: 101, edges: 301 } });
  });

  it('coalesces a burst: queued syncs are superseded by the newest, a running one is left alone', async () => {
    await bootstrapAndWait();
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    const ran: string[] = [];
    syncImpl = async (ctx) => {
      ran.push(ctx.job.commitSha as string);
      if (ran.length === 1) await held;
    };

    const first = (await syncTo('1')).json().job_id as string; // starts running at once
    await tick();
    const second = (await syncTo('2')).json().job_id as string;
    const third = (await syncTo('3')).json().job_id as string;
    const fourth = (await syncTo('4')).json().job_id as string;

    // second and third were queued behind the running one and are replaced by the newest.
    expect((await getJob(second)).json()).toMatchObject({ state: 'superseded', coalesced_into: fourth });
    expect((await getJob(third)).json()).toMatchObject({ state: 'superseded', coalesced_into: fourth });
    expect((await getJob(first)).json().state).toBe('running');

    release();
    await jobs.queue.idle();
    expect(ran).toEqual([sha('1'), sha('4')]);
    expect((await getJob(first)).json().state).toBe('done');
    expect((await getJob(fourth)).json()).toMatchObject({ state: 'done', coalesced_into: null });
  });

  it('does not coalesce syncs of different projects', async () => {
    await bootstrapAndWait({ project: 'p1' });
    await bootstrapAndWait({ project: 'p2' });
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    syncImpl = async () => {
      await held;
    };
    const a = (await syncTo('1', { project: 'p1' })).json().job_id as string;
    const b = (await syncTo('2', { project: 'p2' })).json().job_id as string;
    release();
    await jobs.queue.idle();
    expect((await getJob(a, { project: 'p1' })).json().state).toBe('done');
    expect((await getJob(b, { project: 'p2' })).json().state).toBe('done');
  });

  it.each([
    ['short commit id', { commit_sha: 'abc1234' }],
    ['branch name', { commit_sha: 'main' }],
    ['missing commit', {}],
    ['repo_url on a sync', { commit_sha: 'a'.repeat(40), repo_url: REPO }],
  ])('rejects %s with 422', async (_name, extra) => {
    await bootstrapAndWait();
    const res = await submit({ type: 'sync', ...extra });
    expect(res.statusCode).toBe(422);
    expect(res.json().error_code).toBe('invalid_field');
  });
});

describe('idempotency', () => {
  it('returns the same job for a repeated key and request, without queueing another', async () => {
    const a = await bootstrap({ key: 'create-1' });
    await jobs.queue.idle();
    const b = await bootstrap({ key: 'create-1' });
    expect(b.statusCode).toBe(202);
    expect(b.json().job_id).toBe(a.json().job_id);
    expect(b.json().state).toBe('done');
  });

  it('is a conflict when the key is reused for a different request', async () => {
    await bootstrapAndWait({ key: 'k' });
    const res = await syncTo('a', { key: 'k' });
    expect(res.statusCode).toBe(409);
    expect(res.json().error_code).toBe('job_conflict');
  });

  it('returns a failed job as it is, so a retry needs a new key', async () => {
    bootstrapImpl = async () => {
      throw new Error('boom');
    };
    const first = await bootstrap({ key: 'try-1' });
    await jobs.queue.idle();
    const replay = await bootstrap({ key: 'try-1' });
    expect(replay.json().job_id).toBe(first.json().job_id);
    expect(replay.json().state).toBe('failed');

    bootstrapImpl = async () => undefined;
    const fresh = await bootstrap({ key: 'try-2' });
    expect(fresh.statusCode).toBe(202);
    expect(fresh.json().job_id).not.toBe(first.json().job_id);
  });

  it('keeps keys apart by org and project', async () => {
    const a = await bootstrap({ key: 'same', org: 'orgA' });
    const b = await bootstrap({ key: 'same', org: 'orgB' });
    expect(a.statusCode).toBe(202);
    expect(b.statusCode).toBe(202);
    expect(a.json().job_id).not.toBe(b.json().job_id);
    await jobs.queue.idle();
  });

  it('rejects a key that is not printable ASCII', async () => {
    const res = await bootstrap({ key: 'has space' });
    expect(res.statusCode).toBe(422);
    expect(res.json()).toMatchObject({ error_code: 'invalid_field', field: 'Idempotency-Key' });
  });
});

describe('reconcile', () => {
  it('needs the code:sync scope, and project:admin does not satisfy it', async () => {
    await bootstrapAndWait();
    const denied = await submit({ type: 'reconcile' }, { scopes: ['query', 'project:admin'] });
    expect(denied.statusCode).toBe(403);
    expect(denied.json().error_code).toBe('scope_missing');
  });

  it('is refused for a project that has not been bootstrapped', async () => {
    const res = await submit({ type: 'reconcile' });
    expect(res.statusCode).toBe(409);
    expect(res.json().error_code).toBe('job_conflict');
  });

  it('is accepted for a bootstrapped project, and asking again returns the check already active', async () => {
    await bootstrapAndWait();
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    reconcileImpl = async () => {
      await held;
      return { detail: 'up to date at aaaaaaa' };
    };
    const first = await submit({ type: 'reconcile' });
    expect(first.statusCode).toBe(202);
    const again = await submit({ type: 'reconcile' });
    expect(again.statusCode).toBe(202);
    expect(again.json().job_id).toBe(first.json().job_id);
    release();
    await jobs.queue.idle();
    expect((await getJob(first.json().job_id)).json()).toMatchObject({ type: 'reconcile', state: 'done', detail: 'up to date at aaaaaaa' });

    // Once finished, the next request is a new check.
    const next = await submit({ type: 'reconcile' });
    expect(next.json().job_id).not.toBe(first.json().job_id);
    await jobs.queue.idle();
  });

  it('turns a sync for a pruned project into a reconcile, which rebuilds it', async () => {
    await bootstrapAndWait();
    jobs.store.markPruned('orgA', 'p1');
    const res = await syncTo('a');
    expect(res.statusCode).toBe(202);
    const job = (await getJob(res.json().job_id)).json();
    expect(job.type).toBe('reconcile');
    await jobs.queue.idle();
  });
});

describe('reading a job', () => {
  it('returns 404 for an unknown id, and for a job of another org or another project', async () => {
    const id = await bootstrapAndWait();
    expect((await getJob(id)).statusCode).toBe(200);
    expect((await getJob('job_00000000000000000000000000000000')).statusCode).toBe(404);
    expect((await getJob(id, { org: 'orgB' })).statusCode).toBe(404);
    expect((await getJob(id, { project: 'p2' })).statusCode).toBe(404);
    expect((await getJob(id, { org: 'orgB' })).json().error_code).not.toBe('scope_missing');
  });

  it.each([['query'], ['code:sync'], ['project:admin']])('can be read with scope %s', async (scope) => {
    const id = await bootstrapAndWait();
    expect((await getJob(id, { scopes: [scope] })).statusCode).toBe(200);
  });

  it('is forbidden without any of those scopes', async () => {
    const id = await bootstrapAndWait();
    const res = await getJob(id, { scopes: ['docs:write'] });
    expect(res.statusCode).toBe(403);
    expect(res.json().error_code).toBe('scope_missing');
  });

  it('shows progress while a job runs', async () => {
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    bootstrapImpl = async (ctx) => {
      ctx.update({ phase: 'resolving', progress: 0.6 });
      await held;
    };
    const id = (await bootstrap()).json().job_id as string;
    const running = (await getJob(id)).json();
    expect(running).toMatchObject({ state: 'running', phase: 'resolving', progress: 0.6, finished_at: null });
    expect(Date.parse(running.started_at)).not.toBeNaN();
    release();
    await jobs.queue.idle();
  });
});

describe('request handling', () => {
  it('requires an envelope', async () => {
    const res = await app.inject({ method: 'POST', url: '/internal/v1/code/jobs', payload: { type: 'reconcile' } });
    expect(res.statusCode).toBe(401);
    const get = await app.inject({ method: 'GET', url: '/internal/v1/code/jobs/job_x' });
    expect(get.statusCode).toBe(401);
  });

  it('answers 422 for a malformed or non-object body', async () => {
    const bad = await app.inject({ method: 'POST', url: '/internal/v1/code/jobs', headers: { ...headers({}), 'content-type': 'application/json' }, payload: '{nope' });
    expect(bad.statusCode).toBe(422);
    for (const body of [[], 'x', 5, null]) {
      const res = await app.inject({
        method: 'POST',
        url: '/internal/v1/code/jobs',
        headers: { ...headers({}), 'content-type': 'application/json' },
        payload: JSON.stringify(body),
      });
      expect(res.statusCode, JSON.stringify(body)).toBe(422);
    }
  });

  it('does not accept an org or project in the body', async () => {
    const res = await submit({ type: 'bootstrap', repo_url: REPO, org_id: 'orgB', project_id: 'p9' });
    expect(res.statusCode).toBe(422);
    expect(res.json().field).toBe('org_id');
  });
});
