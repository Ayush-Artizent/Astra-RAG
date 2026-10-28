import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import '../src/env.js';
import { databasePath } from '../src/codegraph.js';
import { collectGarbage, git, GitError, gitEnvironment, looseObjects, remoteHead } from '../src/jobs/git.js';
import { checkProject } from '../src/jobs/health.js';
import { DatabaseSync } from '../src/sqlite.js';
import { gitIn, makeOrigin } from './git-helpers.js';

const lib = createRequire(import.meta.url)('@colbymchenry/codegraph') as {
  CodeGraph: { init(root: string, o: { index: boolean }): Promise<{ close(): void }> };
};

let tmp: string;
let env: NodeJS.ProcessEnv;
beforeAll(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-health-'));
  const emptyConfig = path.join(tmp, 'empty.gitconfig');
  fs.writeFileSync(emptyConfig, '');
  env = gitEnvironment({ allowFileRepos: true, credential: null, repoUrl: null, emptyConfigFile: emptyConfig });
});
afterAll(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

const run = () => ({ env, timeoutMs: 60_000 });

describe('remoteHead', () => {
  it('reads the head of the default branch, or of a named branch, without downloading anything', async () => {
    const origin = makeOrigin(tmp, 'remote-a', { 'a.txt': '1\n' });
    const mainHead = origin.head();
    origin.branch('dev');
    const devHead = origin.commit({ 'b.txt': '2\n' });
    origin.checkout('main');

    const clone = path.join(tmp, 'clone-a');
    await git(['clone', '--quiet', '--', origin.url, clone], run());
    expect(await remoteHead(clone, null, run())).toBe(mainHead);
    expect(await remoteHead(clone, 'main', run())).toBe(mainHead);
    expect(await remoteHead(clone, 'dev', run())).toBe(devHead);

    // It sees a new commit at once.
    origin.checkout('main');
    const newer = origin.commit({ 'c.txt': '3\n' });
    expect(await remoteHead(clone, null, run())).toBe(newer);
  }, 60_000);

  it('says so when the branch does not exist on the remote', async () => {
    const origin = makeOrigin(tmp, 'remote-b', { 'a.txt': '1\n' });
    const clone = path.join(tmp, 'clone-b');
    await git(['clone', '--quiet', '--', origin.url, clone], run());
    await expect(remoteHead(clone, 'no-such-branch', run())).rejects.toThrow(/no branch no-such-branch/);
  }, 60_000);

  it('fails with a git error when the remote is gone', async () => {
    const origin = makeOrigin(tmp, 'remote-c', { 'a.txt': '1\n' });
    const clone = path.join(tmp, 'clone-c');
    await git(['clone', '--quiet', '--', origin.url, clone], run());
    fs.renameSync(origin.dir, `${origin.dir}-away`);
    await expect(remoteHead(clone, null, run())).rejects.toBeInstanceOf(GitError);
  }, 60_000);
});

describe('loose objects and git gc', () => {
  it('counts loose objects, and gc removes the ones nothing needs, keeping the files and the index folder', async () => {
    const origin = makeOrigin(tmp, 'gc-origin', { 'a.txt': 'start\n' });
    const clone = path.join(tmp, 'gc-clone');
    await git(['clone', '--quiet', '--depth', '1', '--', origin.url, clone], run());
    fs.mkdirSync(path.join(clone, '.codegraph'));
    fs.writeFileSync(path.join(clone, '.codegraph', 'codegraph.db'), 'stand-in for the index');

    // Each sync fetches one commit by id and resets to it, as the sync executor does. Small fetches stay loose.
    let last = '';
    for (let i = 0; i < 6; i++) {
      last = origin.commit({ [`f${i}.txt`]: `${'content '.repeat(2000)}${i}\n` });
      await git(['fetch', '--quiet', '--depth', '1', '--no-tags', 'origin', last], { ...run(), cwd: clone });
      await git(['reset', '--hard', '--quiet', last], { ...run(), cwd: clone });
    }
    const before = await looseObjects(clone, run());
    expect(before.looseCount).toBeGreaterThan(10);

    await collectGarbage(clone, run());

    const after = await looseObjects(clone, run());
    expect(after.looseCount).toBeLessThan(before.looseCount);
    expect(after.looseKb).toBeLessThan(before.looseKb);
    // Nothing the project needs was lost.
    expect(gitIn(clone, 'rev-parse', 'HEAD')).toBe(last);
    expect(fs.readFileSync(path.join(clone, 'f5.txt'), 'utf8')).toContain('content');
    expect(fs.readFileSync(path.join(clone, '.codegraph', 'codegraph.db'), 'utf8')).toBe('stand-in for the index');
    expect(gitIn(clone, 'status', '--porcelain')).toBe('?? .codegraph/');
    gitIn(clone, 'fsck', '--no-dangling'); // throws if the repository is damaged
  }, 120_000);

  it('does nothing harmful on a fresh clone', async () => {
    const origin = makeOrigin(tmp, 'gc-origin2', { 'a.txt': 'x\n' });
    const clone = path.join(tmp, 'gc-clone2');
    await git(['clone', '--quiet', '--depth', '1', '--', origin.url, clone], run());
    await collectGarbage(clone, run());
    expect(gitIn(clone, 'rev-parse', 'HEAD')).toBe(origin.head());
  }, 60_000);
});

describe('checkProject', () => {
  async function indexed(name: string, git_ = true) {
    const origin = makeOrigin(tmp, `proj-${name}`, { 'src/a.ts': 'export function alpha() { return 1; }\n' });
    const dir = git_ ? origin.dir : path.join(tmp, `plain-${name}`);
    if (!git_) {
      fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
      fs.writeFileSync(path.join(dir, 'src', 'a.ts'), 'export function alpha() { return 1; }\n');
    }
    (await lib.CodeGraph.init(dir, { index: true })).close();
    return { origin, dir };
  }
  const setMetadata = (dir: string, key: string, value: string) => {
    const db = new DatabaseSync(databasePath(dir));
    db.prepare('UPDATE project_metadata SET value = ? WHERE key = ?').run(value, key);
    db.close();
  };

  it('accepts a whole project and returns the commit its index reflects', async () => {
    const { origin, dir } = await indexed('ok');
    expect(await checkProject(dir)).toEqual({ ok: true, stamp: origin.head() });
  }, 120_000);

  it.each([
    ['a missing folder', () => path.join(tmp, 'never-existed'), /folder is missing/],
  ])('rejects %s', async (_name, dirOf, reason) => {
    const result = await checkProject(dirOf());
    expect(result.ok).toBe(false);
    expect((result as { reason: string }).reason).toMatch(reason);
  });

  it('rejects a folder without git data', async () => {
    const { dir } = await indexed('nogit');
    fs.rmSync(path.join(dir, '.git'), { recursive: true, force: true });
    expect(await checkProject(dir)).toMatchObject({ ok: false, reason: 'the git data is missing' });
  }, 120_000);

  it('rejects a folder without an index', async () => {
    const origin = makeOrigin(tmp, 'proj-noindex', { 'a.ts': 'export const x = 1;\n' });
    expect(await checkProject(origin.dir)).toMatchObject({ ok: false, reason: 'the index is missing' });
  });

  it('rejects an index that cannot be read', async () => {
    const { dir } = await indexed('garbage');
    fs.writeFileSync(databasePath(dir), Buffer.from('this is not a database '.repeat(500)));
    expect(await checkProject(dir)).toMatchObject({ ok: false, reason: 'the index file is damaged' });
  }, 120_000);

  it('rejects a database that opens but has lost its tables', async () => {
    const { dir } = await indexed('tables');
    const db = new DatabaseSync(databasePath(dir));
    db.exec('DROP TABLE project_metadata');
    db.close();
    const result = await checkProject(dir);
    expect(result.ok).toBe(false);
    expect((result as { reason: string }).reason).toMatch(/cannot be (opened|read)|marked|no commit stamp/);
  }, 120_000);

  it.each(['failed', 'indexing'])('rejects an index marked %s (a failed or interrupted run)', async (state) => {
    const { dir } = await indexed(`state-${state}`);
    setMetadata(dir, 'index_state', state);
    expect(await checkProject(dir)).toMatchObject({ ok: false, reason: `the index is marked ${state}` });
  }, 120_000);

  it('accepts a partial index: it finished, it just skipped some files', async () => {
    const { dir } = await indexed('partial');
    setMetadata(dir, 'index_state', 'partial');
    expect(await checkProject(dir)).toMatchObject({ ok: true });
  }, 120_000);

  it('rejects an index with no commit stamp', async () => {
    const { dir } = await indexed('nostamp', false);
    fs.mkdirSync(path.join(dir, '.git')); // looks like a repo, but the index was built outside one
    expect(await checkProject(dir)).toMatchObject({ ok: false, reason: 'the index has no commit stamp' });
  }, 120_000);
});
