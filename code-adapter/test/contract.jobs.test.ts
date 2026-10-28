import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { ProblemError } from '../src/errors.js';
import { createJobSystem, type JobSystem } from '../src/jobs/index.js';
import type { Executor } from '../src/jobs/types.js';
import { validateJobRequest } from '../src/jobs/validate.js';
import { buildServer } from '../src/server.js';
import { conforms, declaredStatuses, type Doc, loadContract, responseSchema, type Schema } from './contract-helpers.js';
import { signedEnvelope, testConfig } from './helpers.js';

// The job endpoints against contracts/code-adapter.openapi.yaml: real responses in every job state, every error
// status declared where it is returned, and the contract's patterns and enums compared with the code.

const JOBS = '/internal/v1/code/jobs';
const REPO = 'https://github.com/acme/app';
const sha = (c: string) => c.repeat(40);

let doc: Doc;
let app: FastifyInstance;
let jobs: JobSystem;
let dataDir: string;
let syncImpl: Executor;
let bootstrapImpl: Executor;

// Reset before every test, so one test that fails part way cannot leave a broken executor for the next.
beforeEach(() => {
  bootstrapImpl = async () => ({ files: 3, symbols: 20, edges: 40 });
  syncImpl = async () => ({ files: 3, symbols: 21, edges: 41 });
});

beforeAll(async () => {
  doc = await loadContract();
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-contract-jobs-'));
  const config = testConfig(dataDir);
  jobs = createJobSystem(config, {
    storeFile: ':memory:',
    executors: { bootstrap: (c) => bootstrapImpl(c), sync: (c) => syncImpl(c) },
  });
  app = buildServer(config, { jobs });
  await app.ready();
});

afterAll(async () => {
  await app.close();
  fs.rmSync(dataDir, { recursive: true, force: true });
});

const all = ['project:admin', 'code:sync', 'query'];
const headers = (project = 'p1', scopes = all, org = 'orgA') => ({ 'x-astra-envelope': signedEnvelope(org, project, scopes) });
const submit = (body: unknown, project = 'p1', scopes = all, org = 'orgA') =>
  app.inject({ method: 'POST', url: JOBS, headers: headers(project, scopes, org), payload: body as object });
const getJob = (id: string, project = 'p1', scopes = all) =>
  app.inject({ method: 'GET', url: `${JOBS}/${id}`, headers: headers(project, scopes) });
const tick = () => new Promise((r) => setImmediate(r));

describe('job responses match the contract', () => {
  it('POST 202 and GET job, for a bootstrap and a sync that finish', async () => {
    const accepted = await submit({ type: 'bootstrap', repo_url: REPO, credentials_ref: 'acme', branch: 'main' }, 'done1');
    expect(accepted.statusCode).toBe(202);
    conforms(responseSchema(doc, JOBS, 'post', 202), accepted.json());
    await jobs.queue.idle();

    const boot = await getJob(accepted.json().job_id, 'done1');
    expect(boot.json().state).toBe('done');
    conforms(responseSchema(doc, `${JOBS}/{job_id}`, 'get', 200), boot.json());

    const sync = await submit({ type: 'sync', commit_sha: sha('a') }, 'done1');
    conforms(responseSchema(doc, JOBS, 'post', 202), sync.json());
    await jobs.queue.idle();
    const synced = await getJob(sync.json().job_id, 'done1');
    expect(synced.json()).toMatchObject({ state: 'done', commit_sha: sha('a') });
    conforms(responseSchema(doc, `${JOBS}/{job_id}`, 'get', 200), synced.json());
  });

  it('GET job while running, with a phase and progress', async () => {
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    bootstrapImpl = async (ctx) => {
      ctx.update({ phase: 'resolving', progress: 0.5 });
      await held;
    };
    const accepted = await submit({ type: 'bootstrap', repo_url: REPO }, 'running1');
    const running = await getJob(accepted.json().job_id, 'running1');
    expect(running.json()).toMatchObject({ state: 'running', phase: 'resolving', progress: 0.5 });
    conforms(responseSchema(doc, `${JOBS}/{job_id}`, 'get', 200), running.json());
    release();
    await jobs.queue.idle();
    bootstrapImpl = async () => ({ files: 3, symbols: 20, edges: 40 });
  });

  it('GET job when failed, and when superseded', async () => {
    bootstrapImpl = async () => {
      throw new Error('fatal: repository not found');
    };
    const failed = await submit({ type: 'bootstrap', repo_url: REPO }, 'failed1');
    await jobs.queue.idle();
    const failedJob = await getJob(failed.json().job_id, 'failed1');
    expect(failedJob.json()).toMatchObject({ state: 'failed', error: 'fatal: repository not found' });
    conforms(responseSchema(doc, `${JOBS}/{job_id}`, 'get', 200), failedJob.json());
    bootstrapImpl = async () => ({ files: 3, symbols: 20, edges: 40 });

    await submit({ type: 'bootstrap', repo_url: REPO }, 'coalesce1');
    await jobs.queue.idle();
    let release!: () => void;
    const held = new Promise<void>((res) => (release = res));
    syncImpl = async () => {
      await held;
    };
    await submit({ type: 'sync', commit_sha: sha('1') }, 'coalesce1');
    await tick();
    const second = (await submit({ type: 'sync', commit_sha: sha('2') }, 'coalesce1')).json().job_id;
    const third = (await submit({ type: 'sync', commit_sha: sha('3') }, 'coalesce1')).json().job_id;
    const superseded = await getJob(second, 'coalesce1');
    expect(superseded.json()).toMatchObject({ state: 'superseded', coalesced_into: third });
    conforms(responseSchema(doc, `${JOBS}/{job_id}`, 'get', 200), superseded.json());
    release();
    await jobs.queue.idle();
    syncImpl = async () => ({ files: 3, symbols: 21, edges: 41 });
  });

  it.each([
    ['403 wrong scope', () => submit({ type: 'bootstrap', repo_url: REPO }, 'e1', ['code:sync']), 403, JOBS, 'post'],
    ['422 bad repo_url', () => submit({ type: 'bootstrap', repo_url: 'http://github.com/a/b' }, 'e2'), 422, JOBS, 'post'],
    ['422 unknown field', () => submit({ type: 'sync', commit_sha: sha('a'), org_id: 'x' }, 'e3'), 422, JOBS, 'post'],
    ['422 short commit', () => submit({ type: 'sync', commit_sha: 'abc1234' }, 'e4'), 422, JOBS, 'post'],
    ['409 sync before bootstrap', () => submit({ type: 'sync', commit_sha: sha('a') }, 'e5'), 409, JOBS, 'post'],
    ['501 reconcile', () => submit({ type: 'reconcile' }, 'e6'), 501, JOBS, 'post'],
    ['401 no envelope', () => app.inject({ method: 'POST', url: JOBS, payload: { type: 'reconcile' } }), 401, JOBS, 'post'],
    ['404 unknown job', () => getJob('job_00000000000000000000000000000000', 'e7'), 404, `${JOBS}/{job_id}`, 'get'],
    ['403 job read without a scope', () => getJob('job_x', 'e8', ['docs:write']), 403, `${JOBS}/{job_id}`, 'get'],
    ['401 job read without envelope', () => app.inject({ method: 'GET', url: `${JOBS}/job_x` }), 401, `${JOBS}/{job_id}`, 'get'],
  ] as const)('error responses are problem+json and declared: %s', async (_name, call, status, pathName, method) => {
    const res = await call();
    expect(res.statusCode).toBe(status);
    expect(res.headers['content-type']).toContain('application/problem+json');
    expect(declaredStatuses(doc, pathName, method), `${method} ${pathName} declares ${status}`).toContain(String(status));
    conforms(doc.components.schemas.Problem as Schema, res.json());
  });

  it('409 when a bootstrap is repeated', async () => {
    await submit({ type: 'bootstrap', repo_url: REPO }, 'dup1');
    await jobs.queue.idle();
    const again = await submit({ type: 'bootstrap', repo_url: REPO }, 'dup1');
    expect(again.statusCode).toBe(409);
    expect(declaredStatuses(doc, JOBS, 'post')).toContain('409');
    conforms(doc.components.schemas.Problem as Schema, again.json());
  });
});

describe('the contract and the code agree about jobs', () => {
  const requestSchema = () => doc.components.schemas.CodeJobRequest as Schema;
  const properties = () => requestSchema().properties as Record<string, Schema & { pattern?: string; maxLength?: number }>;

  const accepted = (body: unknown): boolean => {
    try {
      validateJobRequest(body, { allowedRepoHosts: [], allowFileRepos: false });
      return true;
    } catch (e) {
      if (e instanceof ProblemError) return false;
      throw e;
    }
  };
  const boot = (extra: object) => ({ type: 'bootstrap', repo_url: REPO, ...extra });

  it('lists exactly the request fields the validator knows', () => {
    expect(Object.keys(properties()).sort()).toEqual(['branch', 'commit_sha', 'credentials_ref', 'repo_url', 'type']);
    expect(accepted({ type: 'bootstrap', repo_url: REPO, credentials_ref: 'a', branch: 'main' })).toBe(true);
    expect(accepted({ type: 'sync', commit_sha: sha('a') })).toBe(true);
    expect(accepted({ type: 'reconcile' })).toBe(true);
    expect(accepted({ type: 'bootstrap', repo_url: REPO, not_in_contract: 1 })).toBe(false);
  });

  it('accepts every job type in the contract and no other', () => {
    expect((properties().type!.enum as string[]).sort()).toEqual(['bootstrap', 'reconcile', 'sync']);
    expect(accepted({ type: 'purge' })).toBe(false);
  });

  it('credentials_ref: the validator accepts exactly what the contract pattern and length allow', () => {
    const { pattern } = properties().credentials_ref!;
    const re = new RegExp(pattern as string);
    for (const probe of ['ok_name-1.2', 'has space', 'a/b', 'x'.repeat(64), 'x'.repeat(65), '', 'semi;colon', '../x', 'ünï']) {
      expect(accepted(boot({ credentials_ref: probe })), JSON.stringify(probe)).toBe(re.test(probe));
    }
  });

  it('commit_sha: the validator accepts exactly what the contract pattern allows', () => {
    const { pattern } = properties().commit_sha!;
    const re = new RegExp(pattern as string);
    for (const probe of [sha('a'), sha('A'), 'b'.repeat(64), 'a'.repeat(39), 'a'.repeat(41), 'a'.repeat(63), 'abc1234', 'main', '', `${'a'.repeat(39)}g`]) {
      expect(accepted({ type: 'sync', commit_sha: probe }), JSON.stringify(probe)).toBe(re.test(probe));
    }
  });

  it('branch: the validator is never looser than the contract pattern, and enforces its length', () => {
    const { pattern, maxLength } = properties().branch!;
    const re = new RegExp(pattern as string);
    for (const probe of ['main', 'release/1.2', '-x', '--upload-pack=evil', '/x', 'has space', 'a;b', '', '.hidden']) {
      if (!re.test(probe)) expect(accepted(boot({ branch: probe })), JSON.stringify(probe)).toBe(false);
    }
    expect(accepted(boot({ branch: 'a'.repeat(maxLength as number) }))).toBe(true);
    expect(accepted(boot({ branch: 'a'.repeat((maxLength as number) + 1) }))).toBe(false);
  });

  it('repo_url: enforces the contract length', () => {
    const { maxLength } = properties().repo_url!;
    const prefix = 'https://github.com/';
    expect(accepted(boot({ repo_url: prefix + 'a'.repeat((maxLength as number) - prefix.length) }))).toBe(true);
    expect(accepted(boot({ repo_url: prefix + 'a'.repeat((maxLength as number) - prefix.length + 1) }))).toBe(false);
  });

  it('declares the job states and phases the code can use', () => {
    const source = fs.readFileSync(path.resolve(import.meta.dirname, '../src/jobs/types.ts'), 'utf8');
    const union = (name: string) =>
      [...(new RegExp(`export type ${name} =([^;]+);`).exec(source)?.[1] ?? '').matchAll(/'([a-z_]+)'/g)].map((m) => m[1]!).sort();
    const job = doc.components.schemas.CodeJob!.properties!;
    expect((job.state!.enum as string[]).sort()).toEqual(union('JobState'));
    expect((job.type!.enum as string[]).sort()).toEqual(union('JobType'));
    // `null` (no phase yet) is listed in the contract's enum but is not a phase the code can report.
    expect((job.phase!.enum as (string | null)[]).filter((p) => p !== null).sort()).toEqual(union('JobPhase'));
    expect(job.phase!.enum).toContain(null);
    expect((doc.components.schemas.CodeJobAccepted!.properties!.state!.enum as string[]).sort()).toEqual(union('JobState'));
    expect(union('JobState').length).toBe(5);
  });
});
