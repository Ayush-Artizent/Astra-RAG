import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { ProblemError } from '../src/errors.js';
import { type Handle, type IndexState, ProjectRegistry } from '../src/projects.js';

const DATA = path.resolve('fake-data');

interface FakeHandle extends Handle {
  closed: boolean;
  state: IndexState;
  last: number | null;
}

function fakeFactory() {
  const opened: string[] = [];
  const handles = new Map<string, FakeHandle>();
  let failNext = false;
  let state: IndexState = 'complete';
  let last: number | null = 1;
  return {
    opened,
    handles,
    failNextOpen: () => {
      failNext = true;
    },
    setDefaults: (s: IndexState, l: number | null) => {
      state = s;
      last = l;
    },
    open: async (dir: string): Promise<Handle> => {
      opened.push(dir);
      await Promise.resolve();
      if (failNext) {
        failNext = false;
        throw new Error('open failed');
      }
      const h: FakeHandle = {
        closed: false,
        state,
        last,
        getIndexState: () => h.state,
        getLastIndexedAt: () => h.last,
        close: () => {
          h.closed = true;
        },
      };
      handles.set(dir, h);
      return h;
    },
  };
}

function make(over: { maxOpen?: number; idleMs?: number; initialized?: (d: string) => boolean } = {}) {
  const f = fakeFactory();
  let clock = 1_000;
  const reg = new ProjectRegistry({
    dataDir: DATA,
    maxOpen: over.maxOpen ?? 8,
    idleMs: over.idleMs ?? 0,
    open: f.open,
    initialized: over.initialized ?? (() => true),
    now: () => clock,
  });
  return { f, reg, tick: (ms: number) => (clock += ms) };
}

const dirOf = (org: string, project: string) => path.join(DATA, org, project);

describe('readiness', () => {
  it('reports not_indexed without opening anything when there is no index', async () => {
    const { f, reg } = make({ initialized: () => false });
    const lease = await reg.acquire('orgA', 'p1');
    expect(lease.project).toMatchObject({ ready: false, reason: 'not_indexed' });
    expect(f.opened).toHaveLength(0);
  });

  it.each([
    ['indexing', 1, 'indexing'],
    ['failed', 1, 'failed'],
    [null, null, 'not_indexed'],
  ] as const)('is not ready when index state is %s', async (state, last, reason) => {
    const { f, reg } = make();
    f.setDefaults(state, last);
    const lease = await reg.acquire('orgA', 'p1');
    expect(lease.project).toMatchObject({ ready: false, reason });
  });

  it.each([
    ['complete', 5],
    ['partial', 5],
    [null, 5],
  ] as const)('is ready when index state is %s with an index time', async (state, last) => {
    const { f, reg } = make();
    f.setDefaults(state, last);
    const lease = await reg.acquire('orgA', 'p1');
    expect(lease.project.ready).toBe(true);
    lease.release();
  });

  it('notices a state change on an already open handle (full re-index started)', async () => {
    const { f, reg } = make();
    (await reg.acquire('orgA', 'p1')).release();
    f.handles.get(dirOf('orgA', 'p1'))!.state = 'indexing';
    const lease = await reg.acquire('orgA', 'p1');
    expect(lease.project).toMatchObject({ ready: false, reason: 'indexing' });
  });

  it('does not cache a failed open, so the next request retries', async () => {
    const { f, reg } = make();
    f.failNextOpen();
    const first = await reg.acquire('orgA', 'p1');
    expect(first.project).toMatchObject({ ready: false, reason: 'open_failed' });
    const second = await reg.acquire('orgA', 'p1');
    expect(second.project.ready).toBe(true);
    expect(f.opened).toHaveLength(2);
    second.release();
  });
});

describe('reuse and isolation', () => {
  it('opens a project once and reuses the handle', async () => {
    const { f, reg } = make();
    const a = await reg.acquire('orgA', 'p1');
    const b = await reg.acquire('orgA', 'p1');
    expect(f.opened).toHaveLength(1);
    a.release();
    b.release();
  });

  it('shares one open between concurrent first requests', async () => {
    const { f, reg } = make();
    const leases = await Promise.all([1, 2, 3, 4].map(() => reg.acquire('orgA', 'p1')));
    expect(f.opened).toHaveLength(1);
    leases.forEach((l) => l.release());
  });

  it('keeps the same project id in two orgs apart', async () => {
    const { f, reg } = make();
    const a = await reg.acquire('orgA', 'p1');
    const b = await reg.acquire('orgB', 'p1');
    expect(f.opened.sort()).toEqual([dirOf('orgA', 'p1'), dirOf('orgB', 'p1')].sort());
    a.release();
    b.release();
  });

  it('refuses ids that are not safe directory names', async () => {
    const { reg } = make();
    for (const bad of ['..', 'a/b', '..\\x', '']) {
      await expect(reg.acquire(bad, 'p1')).rejects.toBeInstanceOf(ProblemError);
      await expect(reg.acquire('orgA', bad)).rejects.toBeInstanceOf(ProblemError);
    }
  });
});

describe('lifetime', () => {
  it('closes the least recently used idle handle beyond maxOpen', async () => {
    const { f, reg, tick } = make({ maxOpen: 2 });
    for (const p of ['p1', 'p2', 'p3']) {
      (await reg.acquire('orgA', p)).release();
      tick(10);
    }
    expect(reg.openCount).toBe(2);
    expect(f.handles.get(dirOf('orgA', 'p1'))!.closed).toBe(true);
    expect(f.handles.get(dirOf('orgA', 'p2'))!.closed).toBe(false);
    expect(f.handles.get(dirOf('orgA', 'p3'))!.closed).toBe(false);
  });

  it('never closes a handle that is in use, only after it is released', async () => {
    const { f, reg, tick } = make({ maxOpen: 1 });
    const held = await reg.acquire('orgA', 'p1');
    tick(10);
    (await reg.acquire('orgA', 'p2')).release();
    const h1 = f.handles.get(dirOf('orgA', 'p1'))!;
    expect(h1.closed).toBe(false);
    held.release();
    reg.evict('orgA', 'p1');
    expect(h1.closed).toBe(true);
  });

  it('closes idle handles after idleMs', async () => {
    const { f, reg, tick } = make();
    (await reg.acquire('orgA', 'p1')).release();
    tick(5_000);
    reg.sweepIdle(10_000);
    expect(f.handles.get(dirOf('orgA', 'p1'))!.closed).toBe(false);
    tick(6_000);
    reg.sweepIdle(10_000);
    expect(f.handles.get(dirOf('orgA', 'p1'))!.closed).toBe(true);
    expect(reg.openCount).toBe(0);
  });

  it('defers closing an evicted handle until its last lease is released', async () => {
    const { f, reg } = make();
    const lease = await reg.acquire('orgA', 'p1');
    reg.evict('orgA', 'p1');
    const h = f.handles.get(dirOf('orgA', 'p1'))!;
    expect(h.closed).toBe(false);
    lease.release();
    expect(h.closed).toBe(true);
    lease.release(); // double release is harmless
  });

  it('closes the old handle when the index disappears, and opens a new one after a rebuild', async () => {
    let present = true;
    const { f, reg } = make({ initialized: () => present });
    (await reg.acquire('orgA', 'p1')).release();
    const old = f.handles.get(dirOf('orgA', 'p1'))!;
    present = false;
    expect((await reg.acquire('orgA', 'p1')).project).toMatchObject({ ready: false, reason: 'not_indexed' });
    expect(old.closed).toBe(true);
    present = true;
    const lease = await reg.acquire('orgA', 'p1');
    expect(lease.project.ready).toBe(true);
    expect(f.opened).toHaveLength(2);
    lease.release();
  });

  it('closeAll closes every handle', async () => {
    const { f, reg } = make();
    (await reg.acquire('orgA', 'p1')).release();
    (await reg.acquire('orgB', 'p1')).release();
    reg.closeAll();
    expect([...f.handles.values()].every((h) => h.closed)).toBe(true);
    expect(reg.openCount).toBe(0);
  });

  it('does not keep the process alive with its idle timer', () => {
    const spy = vi.spyOn(globalThis, 'setInterval');
    const reg = new ProjectRegistry({ dataDir: DATA, idleMs: 1000 });
    reg.closeAll();
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});
