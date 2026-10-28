import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createExecutors, createRecoveryFor } from '../src/jobs/executors.js';
import { createJobSystem } from '../src/jobs/index.js';
import { JobStore } from '../src/jobs/store.js';
import { readIndexedCommit } from '../src/jobs/stamp.js';
import { removeDir } from '../src/jobs/workspace.js';
import { ProjectRegistry } from '../src/projects.js';
import { buildServer } from '../src/server.js';
import { gitIn, makeOrigin } from './git-helpers.js';
import { ORG_A_FILES, signedEnvelope, testConfig } from './helpers.js';

// A restart in the middle of a job must not leave a project stuck or inconsistent.

const SLOW = 240_000;
let root: string;
let dataDir: string;
let origins: string;
let storeFile: string;

const config = () => ({ ...testConfig(dataDir), allowFileRepos: true, bootstrapTimeoutMs: SLOW, syncTimeoutMs: SLOW });
const headers = (project: string) => ({ 'x-astra-envelope': signedEnvelope('orgA', project, ['project:admin', 'code:sync', 'query']) });

beforeAll(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-recovery-'));
  dataDir = path.join(root, 'data');
  origins = path.join(root, 'origins');
  storeFile = path.join(root, 'jobs.db');
  fs.mkdirSync(dataDir);
  fs.mkdirSync(origins);
});
afterAll(async () => {
  await removeDir(root);
});

/** A new adapter process: its own registry, job system and server, on the same data and job file. */
async function startAdapter(executors?: ReturnType<typeof createExecutors>) {
  const cfg = config();
  const registry = new ProjectRegistry({ dataDir });
  const jobs = createJobSystem(cfg, {
    storeFile,
    executors: executors ?? createExecutors(cfg, registry),
    recover: createRecoveryFor(cfg, registry),
  });
  const app = buildServer(cfg, { registry, jobs });
  await app.ready(); // starting up runs the recovery
  return { app, jobs, registry };
}

describe('a bootstrap cut off by a crash', () => {
  it('leaves nothing behind: the half-made folder is deleted and the project can be bootstrapped again', async () => {
    const dir = path.join(dataDir, 'orgA', 'crashed');
    // What the dead process left: a half-made clone, a repo record, and a job still marked running.
    fs.mkdirSync(path.join(dir, '.git'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'half-cloned.ts'), 'export const x = 1;');
    const before = new JobStore(storeFile);
    before.addProject({ orgId: 'orgA', projectId: 'crashed', repoUrl: 'https://github.com/acme/app', branch: null, credentialsRef: null });
    const job = before.create({ orgId: 'orgA', projectId: 'crashed', type: 'bootstrap' });
    before.update(job.id, { state: 'running', startedAt: Date.now() });
    before.close();

    const { app, jobs } = await startAdapter();

    expect(fs.existsSync(dir)).toBe(false);
    expect(jobs.store.getProject('orgA', 'crashed')).toBeUndefined();
    const record = (await app.inject({ method: 'GET', url: `/internal/v1/code/jobs/${job.id}`, headers: headers('crashed') })).json();
    expect(record).toMatchObject({ state: 'failed', error: 'The adapter restarted while this job was running' });

    // Without the cleanup this would be a 409, forever.
    const origin = makeOrigin(origins, 'after-crash', { 'a.ts': 'export function recovered() { return 1; }\n' });
    const retry = await app.inject({ method: 'POST', url: '/internal/v1/code/jobs', headers: headers('crashed'), payload: { type: 'bootstrap', repo_url: origin.url } });
    expect(retry.statusCode).toBe(202);
    await jobs.queue.idle();
    expect((await app.inject({ method: 'GET', url: `/internal/v1/code/jobs/${retry.json().job_id}`, headers: headers('crashed') })).json().state).toBe('done');
    await app.close();
  }, SLOW);
});

describe('a sync cut off by a crash', () => {
  it('puts the files back on the commit the index reflects', async () => {
    const origin = makeOrigin(origins, 'sync-crash', ORG_A_FILES);
    const indexed = origin.head();
    const first = await startAdapter();
    const boot = await first.app.inject({ method: 'POST', url: '/internal/v1/code/jobs', headers: headers('s'), payload: { type: 'bootstrap', repo_url: origin.url } });
    expect(boot.statusCode).toBe(202);
    await first.jobs.queue.idle();
    expect(readIndexedCommit(path.join(dataDir, 'orgA', 's'))).toBe(indexed);
    await first.app.close();

    // The dead process had fetched and reset to the new commit, then was killed before the index caught up.
    const next = origin.commit({ 'web/half.ts': 'export function halfDone() { return 1; }\n' });
    const dir = path.join(dataDir, 'orgA', 's');
    const env = { ...process.env, GIT_ALLOW_PROTOCOL: 'file:https' };
    gitIn(dir, '-c', 'protocol.file.allow=always', 'fetch', '--depth', '1', 'origin', next);
    gitIn(dir, 'reset', '--hard', '--quiet', next);
    expect(gitIn(dir, 'rev-parse', 'HEAD')).toBe(next); // files ahead of the index
    expect(readIndexedCommit(dir)).toBe(indexed);
    void env;

    const crashed = new JobStore(storeFile);
    const job = crashed.create({ orgId: 'orgA', projectId: 's', type: 'sync', commitSha: next });
    crashed.update(job.id, { state: 'running', startedAt: Date.now() });
    crashed.close();

    const { app } = await startAdapter();
    expect(gitIn(dir, 'rev-parse', 'HEAD')).toBe(indexed); // back in step
    expect(fs.existsSync(path.join(dir, 'web', 'half.ts'))).toBe(false);
    expect(readIndexedCommit(dir)).toBe(indexed);
    const status = (await app.inject({ method: 'GET', url: '/internal/v1/code/status', headers: headers('s') })).json();
    expect(status).toMatchObject({ state: 'ready', last_synced_sha: indexed });
    await app.close();
  }, SLOW);

  it('leaves a project that is already consistent alone', async () => {
    const dir = path.join(dataDir, 'orgA', 's');
    const head = gitIn(dir, 'rev-parse', 'HEAD');
    const crashed = new JobStore(storeFile);
    const job = crashed.create({ orgId: 'orgA', projectId: 's', type: 'sync', commitSha: 'f'.repeat(40) });
    crashed.update(job.id, { state: 'running', startedAt: Date.now() });
    crashed.close();

    const { app } = await startAdapter();
    expect(gitIn(dir, 'rev-parse', 'HEAD')).toBe(head);
    expect(fs.existsSync(path.join(dir, '.codegraph'))).toBe(true);
    await app.close();
  }, SLOW);
});
