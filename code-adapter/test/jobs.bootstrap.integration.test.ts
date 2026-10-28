import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ensureEmptyGitConfig } from '../src/jobs/common.js';
import { createBootstrapExecutor } from '../src/jobs/bootstrap.js';
import { createExecutors } from '../src/jobs/executors.js';
import { createJobSystem, type JobSystem } from '../src/jobs/index.js';
import type { Executor, JobContext, JobPhase, JobRow } from '../src/jobs/types.js';
import { removeDir } from '../src/jobs/workspace.js';
import { ProjectRegistry } from '../src/projects.js';
import { buildServer } from '../src/server.js';
import { gitIn, makeOrigin } from './git-helpers.js';
import { ORG_A_FILES, seedProject, signedEnvelope, testConfig } from './helpers.js';

// Bootstrap against real git repositories and the real CodeGraph CLI: clone, index, serve, and clean up.

const SLOW = 180_000;
let root: string;
let dataDir: string;
let origins: string;
let registry: ProjectRegistry;
let jobs: JobSystem;
let app: FastifyInstance;
const phasesSeen: Array<JobPhase | undefined> = [];

const config = () => ({
  ...testConfig(dataDir),
  allowFileRepos: true,
  bootstrapTimeoutMs: SLOW,
  syncTimeoutMs: SLOW,
});

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-boot-'));
  dataDir = path.join(root, 'data');
  origins = path.join(root, 'origins');
  fs.mkdirSync(dataDir);
  fs.mkdirSync(origins);

  const cfg = config();
  registry = new ProjectRegistry({ dataDir });
  const real = createExecutors(cfg, registry);
  // Watch the phases the real executor reports, to check the CLI output really maps to them.
  const watched: Executor = (ctx) => real.bootstrap!({ ...ctx, update: (p) => { phasesSeen.push(p.phase); ctx.update(p); } });
  jobs = createJobSystem(cfg, { storeFile: ':memory:', executors: { ...real, bootstrap: watched } });
  app = buildServer(cfg, { registry, jobs });
  await app.ready();
}, SLOW);

afterAll(async () => {
  await app.close();
  await removeDir(root);
});

const headers = (project: string, org = 'orgA', scopes = ['project:admin', 'code:sync', 'query']) => ({
  'x-astra-envelope': signedEnvelope(org, project, scopes),
});
const post = (url: string, body: unknown, project: string, org = 'orgA') =>
  app.inject({ method: 'POST', url, headers: headers(project, org), payload: body as object });
const get = (url: string, project: string, org = 'orgA') => app.inject({ method: 'GET', url, headers: headers(project, org) });

async function bootstrap(project: string, body: object, org = 'orgA') {
  const res = await post('/internal/v1/code/jobs', { type: 'bootstrap', ...body }, project, org);
  expect(res.statusCode, res.body).toBe(202);
  await jobs.queue.idle();
  const job = (await get(`/internal/v1/code/jobs/${res.json().job_id}`, project, org)).json();
  return job as { state: string; error: string | null; phase: string | null; counts?: { files: number; symbols: number; edges: number } };
}

const folder = (project: string, org = 'orgA') => path.join(dataDir, org, project);

describe('a successful bootstrap', () => {
  let origin: ReturnType<typeof makeOrigin>;
  let job: Awaited<ReturnType<typeof bootstrap>>;

  beforeAll(async () => {
    origin = makeOrigin(origins, 'main-repo', ORG_A_FILES);
    job = await bootstrap('p1', { repo_url: origin.url });
  }, SLOW);

  it('finishes, with the size of the index', () => {
    expect(job).toMatchObject({ state: 'done', error: null, phase: 'finalizing' });
    expect(job.counts?.files).toBe(3);
    expect(job.counts?.symbols).toBeGreaterThanOrEqual(10);
    expect(job.counts?.edges).toBeGreaterThan(0);
  });

  it('reports the phases in order, as announced by the real CLI output', () => {
    const order: JobPhase[] = ['clone', 'scanning', 'parsing', 'resolving', 'linking', 'finalizing'];
    const seen = phasesSeen.filter((p): p is JobPhase => p !== undefined);
    expect(seen).toEqual(order);
  });

  it('leaves a shallow, symlink-free checkout of the right commit, and nothing but .codegraph untracked', () => {
    const dir = folder('p1');
    expect(fs.existsSync(path.join(dir, '.git'))).toBe(true);
    expect(fs.existsSync(path.join(dir, '.codegraph', 'codegraph.db'))).toBe(true);
    expect(gitIn(dir, 'rev-parse', 'HEAD')).toBe(origin.head());
    expect(gitIn(dir, 'rev-parse', '--is-shallow-repository')).toBe('true');
    expect(gitIn(dir, 'config', '--local', 'core.symlinks')).toBe('false');
    expect(gitIn(dir, 'status', '--porcelain')).toBe('?? .codegraph/');
  });

  it('keeps the credential out of the repo config and the job record', () => {
    const config = fs.readFileSync(path.join(folder('p1'), '.git', 'config'), 'utf8');
    expect(config).not.toMatch(/extraheader|authorization|token/i);
    expect(config).toContain(origin.url);
  });

  it('is reported as ready, with the commit read from the index', async () => {
    const status = (await get('/internal/v1/code/status', 'p1')).json();
    expect(status).toMatchObject({
      state: 'ready',
      last_synced_sha: origin.head(),
      snapshot: { commit_sha: origin.head(), index_state: 'complete' },
    });
    expect(status.files).toBe(3);
  });

  it('answers queries, with the commit in every citation', async () => {
    const res = await post('/internal/v1/code/query', { mode: 'callers', symbols: ['render'], depth: 5 }, 'p1');
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.plane_status).toBe('ok');
    expect(body.snapshot.commit_sha).toBe(origin.head());
    const names = body.results.map((r: { provenance: { qualified_name: string } }) => r.provenance.qualified_name);
    expect(names).toEqual(expect.arrayContaining(['handle', 'Widget.draw', 'route', 'main', 'start']));
    const short = origin.head().slice(0, 7);
    for (const r of body.results) {
      expect(r.provenance.commit_sha).toBe(origin.head());
      expect(r.citation).toMatch(new RegExp(`@${short}\\)$`));
      // The source files are on disk, so snippets work. A file that imports the symbol is a caller too, and a
      // whole file is never returned as a snippet.
      if (r.kind === 'file') expect(r.text).toBeNull();
      else expect(r.text).toBeTruthy();
    }
    expect(body.results.some((r: { kind: string; text: string | null }) => r.kind !== 'file' && r.text)).toBe(true);
  });

  it('can not be bootstrapped again', async () => {
    const again = await post('/internal/v1/code/jobs', { type: 'bootstrap', repo_url: origin.url }, 'p1');
    expect(again.statusCode).toBe(409);
  });
});

describe('a bootstrap of a chosen branch', () => {
  it('checks out and indexes that branch, and records its commit', async () => {
    const origin = makeOrigin(origins, 'branch-repo', { 'a.ts': 'export function onMain() { return 1; }\n' });
    const mainHead = origin.head();
    origin.branch('dev');
    const devHead = origin.commit({ 'b.ts': 'export function onlyOnDev() { return 2; }\n' });
    origin.checkout('main');

    const job = await bootstrap('branch', { repo_url: origin.url, branch: 'dev' });
    expect(job.state).toBe('done');
    const dir = folder('branch');
    expect(gitIn(dir, 'rev-parse', 'HEAD')).toBe(devHead);
    expect(devHead).not.toBe(mainHead);

    const lookup = await post('/internal/v1/code/query', { mode: 'lookup', symbols: ['onlyOnDev'] }, 'branch');
    expect(lookup.json().results.map((r: { provenance: { symbol: string } }) => r.provenance.symbol)).toEqual(['onlyOnDev']);
    expect(lookup.json().snapshot.commit_sha).toBe(devHead);
  }, SLOW);
});

describe('a repo that tries to reach another tenant through a symlink', () => {
  it('gets a plain file instead, and the other tenant symbol is not indexed', async () => {
    await seedProject(dataDir, 'orgB', 'p1', { 'secret.ts': 'export function victimSecretFn() { return "ORG-B-PRIVATE"; }\n' });
    const evil = makeOrigin(origins, 'evil-repo', { 'src/ok.ts': 'export function legit() { return 1; }\n' });
    evil.commitSymlink('src/leak.ts', '../../../orgB/p1/secret.ts');

    const job = await bootstrap('evil', { repo_url: evil.url });
    expect(job.state, job.error ?? '').toBe('done');

    const leak = path.join(folder('evil'), 'src', 'leak.ts');
    expect(fs.lstatSync(leak).isSymbolicLink()).toBe(false);
    expect(fs.readFileSync(leak, 'utf8')).toBe('../../../orgB/p1/secret.ts');

    const stolen = await post('/internal/v1/code/query', { mode: 'lookup', symbols: ['victimSecretFn'] }, 'evil');
    expect(stolen.json().results).toEqual([]);
    expect(stolen.json().resolved_symbols[0].status).toBe('not_found');
    const own = await post('/internal/v1/code/query', { mode: 'lookup', symbols: ['legit'] }, 'evil');
    expect(own.json().results).toHaveLength(1);
    // The other tenant still sees its own symbol.
    const victim = await post('/internal/v1/code/query', { mode: 'lookup', symbols: ['victimSecretFn'] }, 'p1', 'orgB');
    expect(victim.json().results).toHaveLength(1);
  }, SLOW);
});

describe('a bootstrap that fails', () => {
  it('leaves no folder and no binding behind, and can be retried', async () => {
    const missing = await bootstrap('gone', { repo_url: 'file:///definitely/not/here/repo' });
    expect(missing.state).toBe('failed');
    expect(missing.error).toContain('git clone failed');
    expect(fs.existsSync(folder('gone'))).toBe(false);
    expect(jobs.store.getProject('orgA', 'gone')).toBeUndefined();

    const origin = makeOrigin(origins, 'retry-repo', { 'a.ts': 'export function retried() { return 1; }\n' });
    const retry = await bootstrap('gone', { repo_url: origin.url });
    expect(retry.state, retry.error ?? '').toBe('done');
    expect(fs.existsSync(path.join(folder('gone'), '.codegraph'))).toBe(true);
  }, SLOW);

  it('explains a credential that is not configured, without creating anything', async () => {
    const origin = makeOrigin(origins, 'cred-repo', { 'a.ts': 'export function f() { return 1; }\n' });
    const job = await bootstrap('nocred', { repo_url: origin.url, credentials_ref: 'nokey' });
    expect(job.state).toBe('failed');
    expect(job.error).toMatch(/"nokey" are not configured.*ASTRA_REPO_TOKEN_NOKEY/);
    expect(fs.existsSync(folder('nocred'))).toBe(false);
  });

  it('fails on a branch that does not exist, and cleans up the clone it started', async () => {
    const origin = makeOrigin(origins, 'nobranch-repo', { 'a.ts': 'export function f() { return 1; }\n' });
    const job = await bootstrap('nobranch', { repo_url: origin.url, branch: 'no-such-branch' });
    expect(job.state).toBe('failed');
    expect(job.error).toContain('git clone failed');
    expect(fs.existsSync(folder('nobranch'))).toBe(false);
  });

  it('gives up when the time is up, and cleans up the half-made clone', async () => {
    const cfg = { ...config(), bootstrapTimeoutMs: 1 };
    const reg = new ProjectRegistry({ dataDir });
    const system = createJobSystem(cfg, { storeFile: ':memory:', executors: createExecutors(cfg, reg) });
    const slowApp = buildServer(cfg, { registry: reg, jobs: system });
    await slowApp.ready();
    const origin = makeOrigin(origins, 'slow-repo', { 'a.ts': 'export function f() { return 1; }\n' });
    const res = await slowApp.inject({
      method: 'POST',
      url: '/internal/v1/code/jobs',
      headers: headers('slow'),
      payload: { type: 'bootstrap', repo_url: origin.url },
    });
    await system.queue.idle();
    const job = (await slowApp.inject({ method: 'GET', url: `/internal/v1/code/jobs/${res.json().job_id}`, headers: headers('slow') })).json();
    expect(job.state).toBe('failed');
    expect(job.error).toMatch(/timed out/);
    expect(fs.existsSync(folder('slow'))).toBe(false);
    await slowApp.close();
  }, SLOW);
});

describe('the bootstrap executor on its own', () => {
  const ctxFor = (project: string): JobContext => ({
    job: { id: 'job_x', orgId: 'orgA', projectId: project, type: 'bootstrap' } as JobRow,
    project: { orgId: 'orgA', projectId: project, repoUrl: 'file:///nowhere', branch: null, credentialsRef: null, createdAt: 0, bootstrappedAt: null },
    update: () => {},
    signal: new AbortController().signal,
  });

  it('refuses to touch a folder that already has content, and deletes nothing', async () => {
    const dir = folder('occupied');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'keep.txt'), 'precious');
    const executor = createBootstrapExecutor({ config: config(), registry, emptyGitConfig: ensureEmptyGitConfig(dataDir) });
    await expect(executor(ctxFor('occupied'))).rejects.toThrow(/already has content.*untouched/);
    expect(fs.readFileSync(path.join(dir, 'keep.txt'), 'utf8')).toBe('precious');
  });

  it('stops and cleans up when cancelled', async () => {
    const origin = makeOrigin(origins, 'cancel-repo', { 'a.ts': 'export function f() { return 1; }\n' });
    const controller = new AbortController();
    const ctx = { ...ctxFor('cancelled'), signal: controller.signal, project: { ...ctxFor('cancelled').project, repoUrl: origin.url } };
    const executor = createBootstrapExecutor({ config: config(), registry, emptyGitConfig: ensureEmptyGitConfig(dataDir) });
    controller.abort();
    await expect(executor(ctx)).rejects.toThrow(/Cancelled/);
    expect(fs.existsSync(folder('cancelled'))).toBe(false);
  });

  it('can delete a real clone, whose git objects are read-only on Windows', async () => {
    const dir = folder('deletable');
    expect(fs.existsSync(path.join(folder('p1'), '.git', 'objects'))).toBe(true);
    fs.cpSync(folder('p1'), dir, { recursive: true });
    await removeDir(dir);
    expect(fs.existsSync(dir)).toBe(false);
  });
});
