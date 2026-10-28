import { afterEach, describe, expect, it } from 'vitest';
import { JobQueue } from '../src/jobs/queue.js';
import { JobStore } from '../src/jobs/store.js';
import type { Executor, JobRow, JobType } from '../src/jobs/types.js';

/** A promise the test resolves by hand, so jobs can be held open and released at exact points. */
function gate() {
  let resolve!: () => void;
  const promise = new Promise<void>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const stores: JobStore[] = [];
afterEach(() => {
  for (const s of stores.splice(0)) s.close();
});

function setup(
  executors: Partial<Record<JobType, Executor>>,
  opts: { maxConcurrent?: number; maxBootstraps?: number; onSettled?: (j: JobRow, o: 'done' | 'failed') => void } = {},
) {
  const store = new JobStore(':memory:');
  stores.push(store);
  const queue = new JobQueue({ store, executors, maxConcurrent: opts.maxConcurrent ?? 2, maxBootstraps: opts.maxBootstraps, onSettled: opts.onSettled });
  const add = (project: string, type: JobType = 'sync', org = 'orgA') => {
    if (!store.getProject(org, project)) {
      store.addProject({ orgId: org, projectId: project, repoUrl: 'https://github.com/a/b', branch: null, credentialsRef: null });
    }
    return store.create({ orgId: org, projectId: project, type, commitSha: type === 'sync' ? 'a'.repeat(40) : null });
  };
  return { store, queue, add };
}

const state = (store: JobStore, id: string) => store.get(id)?.state;

describe('running a job', () => {
  it('stores counts, progress and phase, and marks it done', async () => {
    let seenMidRun: JobRow | undefined;
    const { store, queue, add } = setup({
      sync: async (ctx) => {
        ctx.update({ phase: 'parsing', progress: 0.5 });
        seenMidRun = store.get(ctx.job.id);
        return { files: 12, symbols: 340, edges: 900 };
      },
    });
    const job = add('p1');
    queue.kick();
    await queue.idle();

    expect(seenMidRun).toMatchObject({ state: 'running', phase: 'parsing', progress: 0.5 });
    expect(seenMidRun?.startedAt).not.toBeNull();
    expect(store.get(job.id)).toMatchObject({ state: 'done', progress: 1, files: 12, symbols: 340, edges: 900, error: null });
    expect(store.get(job.id)?.finishedAt).not.toBeNull();
  });

  it('records a failure with the message scrubbed of credentials', async () => {
    const { store, queue, add } = setup({
      sync: async () => {
        throw new Error('fatal: unable to access https://oauth2:glpat-SECRET@gitlab.com/a/b.git: denied');
      },
    });
    const job = add('p1');
    queue.kick();
    await queue.idle();
    const row = store.get(job.id);
    expect(row?.state).toBe('failed');
    expect(row?.error).toContain('unable to access');
    expect(row?.error).not.toContain('glpat-SECRET');
  });

  it('fails a job that has no executor', async () => {
    const { store, queue, add } = setup({});
    const job = add('p1');
    queue.kick();
    await queue.idle();
    expect(store.get(job.id)).toMatchObject({ state: 'failed', error: 'No executor for sync jobs' });
  });

  it('fails a job whose project has no repo binding', async () => {
    const { store, queue } = setup({ sync: async () => undefined });
    const job = store.create({ orgId: 'orgA', projectId: 'unbound', type: 'sync' });
    queue.kick();
    await queue.idle();
    expect(store.get(job.id)).toMatchObject({ state: 'failed', error: 'The project has no repo binding' });
  });

  it('tells the settle hook the outcome, and survives a hook that throws', async () => {
    const seen: string[] = [];
    const { store, queue, add } = setup(
      { sync: async (ctx) => { if (ctx.project.projectId === 'bad') throw new Error('boom'); } },
      {
        onSettled: (job, outcome) => {
          seen.push(`${job.projectId}:${outcome}:${job.state}`);
          throw new Error('hook failure');
        },
      },
    );
    const good = add('good');
    const bad = add('bad');
    queue.kick();
    await queue.idle();
    expect(seen.sort()).toEqual(['bad:failed:failed', 'good:done:done']);
    expect(state(store, good.id)).toBe('done');
    expect(state(store, bad.id)).toBe('failed');
  });
});

describe('scheduling rules', () => {
  it('never runs two jobs of one project at once, and runs them in the order created', async () => {
    const order: string[] = [];
    let active = 0;
    let maxActive = 0;
    const gates = [gate(), gate(), gate()];
    let n = 0;
    const { store, queue, add } = setup(
      {
        sync: async (ctx) => {
          const i = n++;
          active++;
          maxActive = Math.max(maxActive, active);
          order.push(ctx.job.id);
          await (gates[i] as ReturnType<typeof gate>).promise;
          active--;
        },
      },
      { maxConcurrent: 5 },
    );
    const jobs = [add('p1'), add('p1'), add('p1')];
    queue.kick();
    expect(store.running().map((j) => j.id)).toEqual([jobs[0]!.id]);
    gates[0]!.resolve();
    await Promise.resolve();
    await new Promise((r) => setImmediate(r));
    expect(store.running().map((j) => j.id)).toEqual([jobs[1]!.id]);
    gates[1]!.resolve();
    await new Promise((r) => setImmediate(r));
    gates[2]!.resolve();
    await queue.idle();

    expect(maxActive).toBe(1);
    expect(order).toEqual(jobs.map((j) => j.id));
    expect(jobs.every((j) => state(store, j.id) === 'done')).toBe(true);
  });

  it('limits how many jobs run at once across projects', async () => {
    let active = 0;
    let maxActive = 0;
    const gates = new Map<string, ReturnType<typeof gate>>();
    const { store, queue, add } = setup(
      {
        sync: async (ctx) => {
          active++;
          maxActive = Math.max(maxActive, active);
          const g = gate();
          gates.set(ctx.job.projectId, g);
          await g.promise;
          active--;
        },
      },
      { maxConcurrent: 2 },
    );
    const jobs = ['p1', 'p2', 'p3', 'p4', 'p5'].map((p) => add(p));
    queue.kick();
    expect(store.running()).toHaveLength(2);
    expect(store.queued()).toHaveLength(3);

    const finish = async (project: string) => {
      gates.get(project)!.resolve();
      await new Promise((r) => setImmediate(r));
    };
    await finish('p1');
    expect(store.running()).toHaveLength(2);
    await finish('p2');
    await finish('p3');
    await finish('p4');
    await finish('p5');
    await queue.idle();
    expect(maxActive).toBe(2);
    expect(jobs.every((j) => state(store, j.id) === 'done')).toBe(true);
  });

  it('runs one bootstrap at a time but lets a sync run beside it', async () => {
    const gates = new Map<string, ReturnType<typeof gate>>();
    const run: Executor = async (ctx) => {
      const g = gate();
      gates.set(ctx.job.projectId, g);
      await g.promise;
    };
    const { store, queue, add } = setup({ bootstrap: run, sync: run }, { maxConcurrent: 3 });
    const b1 = add('p1', 'bootstrap');
    const b2 = add('p2', 'bootstrap');
    const s3 = add('p3', 'sync');
    queue.kick();

    expect(state(store, b1.id)).toBe('running');
    expect(state(store, b2.id)).toBe('queued'); // waits for the other bootstrap, even though a slot is free
    expect(state(store, s3.id)).toBe('running');

    gates.get('p1')!.resolve();
    await new Promise((r) => setImmediate(r));
    expect(state(store, b2.id)).toBe('running');

    gates.get('p2')!.resolve();
    gates.get('p3')!.resolve();
    await queue.idle();
    expect([b1, b2, s3].every((j) => state(store, j.id) === 'done')).toBe(true);
  });

  it('starts a queued job as soon as the one ahead of it finishes, without being kicked again', async () => {
    const first = gate();
    let calls = 0;
    const { store, queue, add } = setup({
      sync: async () => {
        if (calls++ === 0) await first.promise;
      },
    });
    const a = add('p1');
    const b = add('p1');
    queue.kick();
    expect(state(store, b.id)).toBe('queued');
    first.resolve();
    await queue.idle();
    expect([a, b].map((j) => state(store, j.id))).toEqual(['done', 'done']);
  });
});

describe('start and stop', () => {
  it('on start, fails jobs a dead process left running, then runs what is queued', async () => {
    const ran: string[] = [];
    const { store, queue, add } = setup({ sync: async (ctx) => void ran.push(ctx.job.id) });
    const stale = add('p1');
    store.update(stale.id, { state: 'running', startedAt: 1 });
    const waiting = add('p2');

    await queue.start();
    await queue.idle();

    expect(store.get(stale.id)).toMatchObject({ state: 'failed', error: 'The adapter restarted while this job was running' });
    expect(ran).toEqual([waiting.id]);
  });

  it('cleans up after interrupted jobs before any queued job starts, and tells the settle hook', async () => {
    const events: string[] = [];
    const store = new JobStore(':memory:');
    stores.push(store);
    const queue = new JobQueue({
      store,
      maxConcurrent: 2,
      executors: { sync: async (ctx) => void events.push(`run ${ctx.job.projectId}`) },
      recover: async (job) => {
        await new Promise((r) => setTimeout(r, 20)); // cleanup takes a moment
        events.push(`recover ${job.projectId}`);
      },
      onSettled: (job, outcome) => void events.push(`settled ${job.projectId} ${outcome}`),
    });
    for (const p of ['p1', 'p2', 'p3']) store.addProject({ orgId: 'orgA', projectId: p, repoUrl: 'https://github.com/a/b', branch: null, credentialsRef: null });
    const crashed = store.create({ orgId: 'orgA', projectId: 'p1', type: 'bootstrap' });
    store.update(crashed.id, { state: 'running' });
    const crashed2 = store.create({ orgId: 'orgA', projectId: 'p2', type: 'sync', commitSha: 'a'.repeat(40) });
    store.update(crashed2.id, { state: 'running' });
    store.create({ orgId: 'orgA', projectId: 'p3', type: 'sync', commitSha: 'b'.repeat(40) });

    await queue.start();
    await queue.idle();

    expect(events.slice(0, 4)).toEqual(['recover p1', 'settled p1 failed', 'recover p2', 'settled p2 failed']);
    expect(events.slice(4)).toEqual(['run p3', 'settled p3 done']);
  });

  it('still starts when cleanup fails, and records why on the job', async () => {
    const ran: string[] = [];
    const store = new JobStore(':memory:');
    stores.push(store);
    const queue = new JobQueue({
      store,
      maxConcurrent: 2,
      executors: { sync: async (ctx) => void ran.push(ctx.job.projectId) },
      recover: async () => {
        throw new Error('EBUSY: folder in use');
      },
    });
    for (const p of ['p1', 'p2']) store.addProject({ orgId: 'orgA', projectId: p, repoUrl: 'https://github.com/a/b', branch: null, credentialsRef: null });
    const crashed = store.create({ orgId: 'orgA', projectId: 'p1', type: 'bootstrap' });
    store.update(crashed.id, { state: 'running' });
    store.create({ orgId: 'orgA', projectId: 'p2', type: 'sync', commitSha: 'a'.repeat(40) });

    await queue.start();
    await queue.idle();

    expect(ran).toEqual(['p2']);
    expect(store.get(crashed.id)).toMatchObject({ state: 'failed' });
    expect(store.get(crashed.id)?.error).toContain('cleanup failed: EBUSY: folder in use');
  });

  it('on stop, aborts running jobs, leaves queued ones queued, and starts nothing more', async () => {
    const started = gate();
    const { store, queue, add } = setup({
      sync: (ctx) =>
        new Promise<void>((_resolve, reject) => {
          started.resolve();
          ctx.signal.addEventListener('abort', () => reject(new Error('killed child process')));
        }),
    });
    const running = add('p1');
    const behind = add('p1');
    queue.kick();
    await started.promise;
    expect(queue.isRunning(running.id)).toBe(true);

    await queue.stop();

    expect(store.get(running.id)).toMatchObject({ state: 'failed', error: 'Cancelled: the adapter is shutting down' });
    expect(state(store, behind.id)).toBe('queued');
    queue.kick();
    expect(state(store, behind.id)).toBe('queued');
  });

  it('does not hang on shutdown when a job ignores the abort signal, and records it as failed', async () => {
    const started = gate();
    const never = gate();
    const { store, queue, add } = setup({
      sync: async () => {
        started.resolve();
        await never.promise; // never listens to the abort signal
      },
    });
    const job = add('p1');
    queue.kick();
    await started.promise;

    const t = Date.now();
    await queue.stop(50);
    expect(Date.now() - t).toBeLessThan(2000);
    expect(store.get(job.id)).toMatchObject({ state: 'failed' });
    expect(store.get(job.id)?.error).toContain('did not stop in time');
  });

  it('does not crash when a job finishes after the store was closed', async () => {
    const started = gate();
    const late = gate();
    const { store, queue, add } = setup({
      sync: async () => {
        started.resolve();
        await late.promise;
      },
    });
    add('p1');
    queue.kick();
    await started.promise;
    await queue.stop(20);
    store.close();
    late.resolve(); // the stubborn job completes now, against a closed store
    await new Promise((r) => setTimeout(r, 30));
    // Reaching here without an unhandled rejection is the assertion; vitest fails the run on one.
    expect(queue.isRunning('anything')).toBe(false);
    stores.splice(stores.indexOf(store), 1);
  });

  it('idle resolves at once when there is nothing to do', async () => {
    const { queue } = setup({});
    await queue.idle();
  });
});
