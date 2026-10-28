import { describe, expect, it } from 'vitest';
import { runProcess } from '../src/jobs/process.js';

const node = process.execPath;
const run = (script: string, opts: Partial<Parameters<typeof runProcess>[2]> = {}) =>
  runProcess(node, ['-e', script], { timeoutMs: 20_000, ...opts });

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
const pidsIn = (text: string) => [...text.matchAll(/pid:(\d+)/g)].map((m) => Number(m[1]));
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function allDeadSoon(pids: number[], withinMs = 5000): Promise<boolean> {
  const end = Date.now() + withinMs;
  while (Date.now() < end) {
    if (pids.every((p) => !alive(p))) return true;
    await sleep(100);
  }
  return false;
}

describe('runProcess', () => {
  it('captures stdout, stderr and the exit code', async () => {
    const r = await run('console.log("out"); console.error("err"); process.exit(3)');
    expect(r).toMatchObject({ code: 3, timedOut: false, aborted: false });
    expect(r.stdout.trim()).toBe('out');
    expect(r.stderr.trim()).toBe('err');
  });

  it('uses the given working directory and environment, and nothing else from the parent', async () => {
    const r = await run('console.log(process.cwd() + "|" + process.env.ASTRA_TEST_VAR + "|" + process.env.ASTRA_PARENT_ONLY)', {
      cwd: process.cwd(),
      env: { ...process.env, ASTRA_TEST_VAR: 'hello', ASTRA_PARENT_ONLY: undefined },
    });
    expect(r.stdout.trim()).toBe(`${process.cwd()}|hello|undefined`);
  });

  it('reports each line as it arrives, including partial lines, carriage returns and both streams', async () => {
    const lines: string[] = [];
    await run('process.stdout.write("one\\ntw"); process.stdout.write("o\\r\\nthree\\rfour"); console.error("err1\\nerr2")', {
      onLine: (l) => lines.push(l),
    });
    expect(lines.sort()).toEqual(['err1', 'err2', 'four', 'one', 'three', 'two']);
  });

  it('does not wait for stdin', async () => {
    const r = await run('process.stdin.on("data", () => {}); process.stdin.on("end", () => console.log("stdin closed"))');
    expect(r.stdout.trim()).toBe('stdin closed');
  });

  it('caps how much it keeps, keeping the end of stderr', async () => {
    const r = await run('console.error("x".repeat(100000) + "THE-END")');
    expect(r.stderr.length).toBeLessThanOrEqual(16 * 1024);
    expect(r.stderr).toContain('THE-END');
  });

  it('rejects when the command cannot be started', async () => {
    await expect(runProcess('definitely-not-a-real-command-xyz', [], { timeoutMs: 5000 })).rejects.toThrow(/ENOENT/);
  });
});

describe('runProcess stops what it started', () => {
  const tree = `
    const { spawn } = require('child_process');
    const grandchild = spawn(process.execPath, ['-e', 'console.log("pid:" + process.pid); setInterval(() => {}, 1000)'], { stdio: ['ignore', 'inherit', 'inherit'] });
    console.log('pid:' + process.pid);
    setInterval(() => {}, 1000);
  `;

  it('kills the process and its children when the time is up', async () => {
    const started = Date.now();
    const r = await run(tree, { timeoutMs: 1500 });
    expect(r.timedOut).toBe(true);
    expect(r.aborted).toBe(false);
    expect(Date.now() - started).toBeLessThan(15_000);
    const pids = pidsIn(r.stdout);
    expect(pids.length).toBe(2); // the parent and the grandchild both reported in
    expect(await allDeadSoon(pids)).toBe(true);
  });

  it('kills the process and its children when aborted, and reports it', async () => {
    const controller = new AbortController();
    const pending = run(tree, { signal: controller.signal });
    await sleep(1500);
    controller.abort();
    const r = await pending;
    expect(r.aborted).toBe(true);
    expect(r.timedOut).toBe(false);
    const pids = pidsIn(r.stdout);
    expect(pids.length).toBe(2);
    expect(await allDeadSoon(pids)).toBe(true);
  });

  it('does not start anything when the signal is already aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    const r = await run('console.log("should not run")', { signal: controller.signal });
    expect(r).toMatchObject({ aborted: true, code: null, stdout: '' });
  });
});
