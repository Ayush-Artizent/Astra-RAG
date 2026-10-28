import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { FastifyInstance } from 'fastify';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { NotReadyProject, ReadyProject } from '../src/projects.js';
import { buildServer } from '../src/server.js';
import { buildStatus } from '../src/status.js';
import {
  commitShaFor,
  ORG_A_FILES,
  ORG_A_SHA,
  ORG_B_FILES,
  seedProject,
  signedEnvelope,
  testConfig,
} from './helpers.js';

const notReady = (reason: NotReadyProject['reason'], indexState: NotReadyProject['indexState']): NotReadyProject => ({
  ready: false,
  dir: '/x',
  reason,
  indexState,
});

describe('buildStatus for a project that is not ready', () => {
  it.each([
    ['not_indexed', null, 'not_indexed', 'not_indexed', null],
    ['indexing', 'indexing', 'indexing', 'indexing', null],
    ['failed', 'failed', 'error', 'failed', 'The last index run failed'],
    ['open_failed', null, 'error', 'failed', 'The index could not be opened'],
  ] as const)('%s -> state %s', (reason, indexState, state, snapshotState, error) => {
    const s = buildStatus(notReady(reason, indexState), 'abc1234');
    expect(s.state).toBe(state);
    expect(s.error).toBe(error);
    // A project that is not ready never claims a commit, a sync time or counts.
    expect(s.snapshot).toEqual({ commit_sha: null, index_time: null, index_state: snapshotState, sync_in_progress: false });
    expect(s.last_synced_sha).toBeNull();
    expect(s.last_sync).toBeNull();
    expect(s).not.toHaveProperty('files');
    expect(s).not.toHaveProperty('symbols');
  });
});

describe('buildStatus while jobs run', () => {
  it('calls a project with no index yet `indexing` while its bootstrap is running or queued', () => {
    const s = buildStatus(notReady('not_indexed', null), null, { id: 'job_1', running: true }, true);
    expect(s).toMatchObject({ state: 'indexing', active_job: 'job_1', snapshot: { index_state: 'not_indexed', sync_in_progress: true } });
    expect(buildStatus(notReady('not_indexed', null), null, { id: 'job_2', running: false }).state).toBe('indexing');
    expect(buildStatus(notReady('not_indexed', null), null, null).state).toBe('not_indexed');
  });

  it('does not hide a failed index behind an active job', () => {
    expect(buildStatus(notReady('failed', 'failed'), null, { id: 'job_3', running: true }).state).toBe('error');
  });

  it('shows the job and the sync flag on a ready project, without changing its state', () => {
    const ready: ReadyProject = {
      ready: true,
      dir: '/x',
      indexState: 'complete',
      lastIndexedAt: 1,
      cg: { getStats: () => ({ nodeCount: 1, edgeCount: 1, fileCount: 1, nodesByKind: { function: 1 } }) } as unknown as ReadyProject['cg'],
    };
    const during = buildStatus(ready, 'abc', { id: 'job_4', running: true }, true);
    expect(during).toMatchObject({ state: 'ready', active_job: 'job_4', snapshot: { sync_in_progress: true } });
    const idle = buildStatus(ready, 'abc');
    expect(idle).toMatchObject({ state: 'ready', active_job: null, snapshot: { sync_in_progress: false } });
  });
});

describe('buildStatus for a ready project', () => {
  const ready = (over: Partial<ReadyProject> = {}): ReadyProject => ({
    ready: true,
    dir: '/x',
    indexState: 'complete',
    lastIndexedAt: Date.UTC(2026, 9, 26, 9, 41, 44),
    cg: {
      getStats: () => ({
        nodeCount: 100,
        edgeCount: 250,
        fileCount: 12,
        nodesByKind: { file: 12, import: 20, function: 40, method: 20, class: 8 },
      }),
    } as unknown as ReadyProject['cg'],
    ...over,
  });

  it('reports counts, leaving files and imports out of symbols', () => {
    const s = buildStatus(ready(), 'a1b2c3d');
    expect(s).toMatchObject({
      state: 'ready',
      files: 12,
      symbols: 68,
      edges: 250,
      last_synced_sha: 'a1b2c3d',
      last_sync: '2026-10-26T09:41:44.000Z',
      error: null,
      active_job: null,
      snapshot: { commit_sha: 'a1b2c3d', index_time: '2026-10-26T09:41:44.000Z', index_state: 'complete' },
    });
  });

  it('allows an unknown commit and index time', () => {
    const s = buildStatus(ready({ lastIndexedAt: null, indexState: 'partial' }), null);
    expect(s.state).toBe('ready');
    expect(s.last_synced_sha).toBeNull();
    expect(s.last_sync).toBeNull();
    expect(s.snapshot.index_state).toBe('partial');
  });
});

describe('GET /internal/v1/code/status', () => {
  let dataDir: string;
  let app: FastifyInstance;

  beforeAll(async () => {
    dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-status-'));
    await seedProject(dataDir, 'orgA', 'p1', ORG_A_FILES);
    await seedProject(dataDir, 'orgB', 'p1', ORG_B_FILES);
    app = buildServer(testConfig(dataDir), { commitSha: commitShaFor });
    await app.ready();
  }, 180_000);

  afterAll(async () => {
    await app.close();
    fs.rmSync(dataDir, { recursive: true, force: true });
  });

  const status = (org: string, project: string, scopes?: string[]) =>
    app.inject({
      method: 'GET',
      url: '/internal/v1/code/status',
      headers: { 'x-astra-envelope': signedEnvelope(org, project, scopes) },
    });

  it('reports a ready project with real counts and its commit', async () => {
    const res = await status('orgA', 'p1');
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body).toMatchObject({
      state: 'ready',
      last_synced_sha: ORG_A_SHA,
      error: null,
      snapshot: { commit_sha: ORG_A_SHA, index_state: 'complete' },
    });
    expect(body.files).toBe(3);
    expect(body.symbols).toBeGreaterThanOrEqual(10); // 6 functions + 2 classes + 3 methods, plus the token helpers
    expect(body.edges).toBeGreaterThan(0);
    expect(Date.parse(body.last_sync)).not.toBeNaN();
  });

  it('reports not_indexed with 200, not an error', async () => {
    const res = await status('orgA', 'p2');
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      state: 'not_indexed',
      snapshot: { commit_sha: null, index_time: null, index_state: 'not_indexed' },
      error: null,
    });
  });

  it('keeps orgs apart: the same project id gives each org its own counts and commit', async () => {
    const a = (await status('orgA', 'p1')).json();
    const b = (await status('orgB', 'p1')).json();
    expect(b.files).toBe(1);
    expect(b.files).not.toBe(a.files);
    expect(b.last_synced_sha).toBeNull();
    expect(JSON.stringify(b)).not.toContain(ORG_A_SHA);
  });

  it('requires an envelope and the query scope', async () => {
    const none = await app.inject({ method: 'GET', url: '/internal/v1/code/status' });
    expect(none.statusCode).toBe(401);
    const wrong = await status('orgA', 'p1', ['code:sync']);
    expect(wrong.statusCode).toBe(403);
    expect(wrong.json().error_code).toBe('scope_missing');
  });
});
