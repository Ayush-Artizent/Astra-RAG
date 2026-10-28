import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import '../src/env.js';
import { codegraphLauncher, phaseOfLine } from '../src/jobs/codegraph-cli.js';
import { credentialEnvName, resolveCredential } from '../src/jobs/credentials.js';
import { git, GitError, gitEnvironment, samePath, topLevel } from '../src/jobs/git.js';
import { readIndexedCommit } from '../src/jobs/stamp.js';
import { findSymlinks, isNonEmptyDir, removeDir } from '../src/jobs/workspace.js';
import { makeOrigin } from './git-helpers.js';

const lib = createRequire(import.meta.url)('@colbymchenry/codegraph') as {
  CodeGraph: { init(root: string, o: { index: boolean }): Promise<{ close(): void }> };
};

let tmp: string;
let emptyConfig: string;
beforeAll(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-gitunit-'));
  emptyConfig = path.join(tmp, 'empty.gitconfig');
  fs.writeFileSync(emptyConfig, '');
});
afterAll(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

describe('credentials', () => {
  it('names the environment variable after the reference', () => {
    expect(credentialEnvName('acme')).toBe('ASTRA_REPO_TOKEN_ACME');
    expect(credentialEnvName('acme-prod.v2')).toBe('ASTRA_REPO_TOKEN_ACME_PROD_V2');
  });

  it('turns a bare token into basic auth with the default user, and keeps an explicit user', () => {
    const bare = resolveCredential('acme', { ASTRA_REPO_TOKEN_ACME: 'ghp_abc123' });
    expect(bare?.header).toBe(`Authorization: Basic ${Buffer.from('x-access-token:ghp_abc123').toString('base64')}`);
    const user = resolveCredential('gl', { ASTRA_REPO_TOKEN_GL: 'oauth2:glpat-xyz789' });
    expect(user?.header).toBe(`Authorization: Basic ${Buffer.from('oauth2:glpat-xyz789').toString('base64')}`);
  });

  it('lists every form of the secret so errors can be scrubbed', () => {
    const c = resolveCredential('acme', { ASTRA_REPO_TOKEN_ACME: 'ghp_abc123' });
    const encoded = Buffer.from('x-access-token:ghp_abc123').toString('base64');
    expect(c?.secrets).toEqual(expect.arrayContaining(['ghp_abc123', 'x-access-token:ghp_abc123', encoded]));
  });

  it('is null for a public repo, and explains a reference that is not configured', () => {
    expect(resolveCredential(null, {})).toBeNull();
    expect(() => resolveCredential('missing', {})).toThrow(/not configured.*ASTRA_REPO_TOKEN_MISSING/);
    expect(() => resolveCredential('empty', { ASTRA_REPO_TOKEN_EMPTY: '' })).toThrow(/not configured/);
  });
});

describe('gitEnvironment', () => {
  const secret = resolveCredential('acme', { ASTRA_REPO_TOKEN_ACME: 'ghp_SECRETVALUE' });
  const base = {
    PATH: '/usr/bin',
    HOME: '/home/x',
    GIT_DIR: '/elsewhere/.git',
    GIT_WORK_TREE: '/elsewhere',
    git_ssh_command: 'ssh -i key',
    GIT_SSH_COMMAND: 'ssh -i key',
    GIT_ALLOW_PROTOCOL: 'ssh',
  };

  it('does not inherit git settings from the machine, and keeps ordinary variables', () => {
    const env = gitEnvironment({ allowFileRepos: false, credential: null, repoUrl: null, emptyConfigFile: emptyConfig }, base);
    expect(env.PATH).toBe('/usr/bin');
    expect(env.HOME).toBe('/home/x');
    expect(env.GIT_DIR).toBeUndefined();
    expect(env.GIT_WORK_TREE).toBeUndefined();
    expect(env.GIT_SSH_COMMAND).toBeUndefined();
    expect(env.git_ssh_command).toBeUndefined();
    expect(env.GIT_CONFIG_NOSYSTEM).toBe('1');
    expect(env.GIT_CONFIG_GLOBAL).toBe(emptyConfig);
    expect(env.GIT_TERMINAL_PROMPT).toBe('0');
    expect(env.GCM_INTERACTIVE).toBe('never');
  });

  it('allows only https, and file only when asked', () => {
    const make = (allowFileRepos: boolean) =>
      gitEnvironment({ allowFileRepos, credential: null, repoUrl: null, emptyConfigFile: emptyConfig }, base).GIT_ALLOW_PROTOCOL;
    expect(make(false)).toBe('https');
    expect(make(true)).toBe('https:file');
  });

  it('sends the token only to the origin of the repo, as a header set through the environment', () => {
    const env = gitEnvironment({ allowFileRepos: false, credential: secret, repoUrl: 'https://github.com/acme/app', emptyConfigFile: emptyConfig }, base);
    expect(env.GIT_CONFIG_COUNT).toBe('1');
    expect(env.GIT_CONFIG_KEY_0).toBe('http.https://github.com/.extraheader');
    expect(env.GIT_CONFIG_VALUE_0).toBe(secret?.header);
    // The secret appears in exactly one variable.
    const holders = Object.entries(env).filter(([, v]) => v?.includes(Buffer.from('x-access-token:ghp_SECRETVALUE').toString('base64')));
    expect(holders.map(([k]) => k)).toEqual(['GIT_CONFIG_VALUE_0']);
    expect(Object.values(env).some((v) => v?.includes('ghp_SECRETVALUE'))).toBe(false);
  });

  it('sends no credential for a non-https remote, or when there is none', () => {
    const file = gitEnvironment({ allowFileRepos: true, credential: secret, repoUrl: 'file:///srv/repo', emptyConfigFile: emptyConfig }, base);
    expect(file.GIT_CONFIG_COUNT).toBeUndefined();
    const none = gitEnvironment({ allowFileRepos: false, credential: null, repoUrl: 'https://github.com/a/b', emptyConfigFile: emptyConfig }, base);
    expect(none.GIT_CONFIG_COUNT).toBeUndefined();
  });
});

describe('git', () => {
  const env = () => gitEnvironment({ allowFileRepos: true, credential: null, repoUrl: null, emptyConfigFile: emptyConfig });

  it('returns trimmed output and finds the root of a working tree', async () => {
    const origin = makeOrigin(tmp, 'origin-a', { 'a.txt': 'x\n' });
    const head = await git(['rev-parse', 'HEAD'], { cwd: origin.dir, env: env(), timeoutMs: 30_000 });
    expect(head).toBe(origin.head());
    const root = await topLevel(origin.dir, { env: env(), timeoutMs: 30_000 });
    expect(samePath(root, origin.dir)).toBe(true);
  });

  it('reports a folder inside another repo as having that repo as its root', async () => {
    const origin = makeOrigin(tmp, 'origin-b', { 'a.txt': 'x\n' });
    const inner = path.join(origin.dir, 'nested');
    fs.mkdirSync(inner);
    const root = await topLevel(inner, { env: env(), timeoutMs: 30_000 });
    expect(samePath(root, origin.dir)).toBe(true);
    expect(samePath(root, inner)).toBe(false);
  });

  it('removes secrets from the error text of a failed command', async () => {
    const bad = `file:///no/such/ghp_TOPSECRET99/repo`;
    let error: unknown;
    try {
      await git(['clone', '--', bad, path.join(tmp, 'never')], { env: env(), timeoutMs: 30_000, secrets: ['ghp_TOPSECRET99'] });
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(GitError);
    const message = (error as Error).message;
    expect(message).toContain('git clone failed');
    expect(message).not.toContain('ghp_TOPSECRET99');
    expect(message).toContain('***');
  });

  it('stops a command that runs too long', async () => {
    await expect(git(['clone', '--', 'file:///no/such/repo', path.join(tmp, 'never2')], { env: env(), timeoutMs: 1 })).rejects.toThrow(/timed out|failed/);
  });

  it('names the subcommand in errors, not the value of a -c option', async () => {
    const { subcommand } = await import('../src/jobs/git.js');
    expect(subcommand(['-c', 'core.symlinks=false', 'clone', '--depth', '1'])).toBe('clone');
    expect(subcommand(['-c', 'a=b', '-c', 'c=d', 'fetch'])).toBe('fetch');
    expect(subcommand(['--version'])).toBe('command');
    expect(subcommand([])).toBe('command');
  });

  it('samePath ignores slash direction and trailing slashes', () => {
    expect(samePath('C:/a/b', 'C:\\a\\b\\')).toBe(process.platform === 'win32');
    expect(samePath(tmp, `${tmp}${path.sep}`)).toBe(true);
    expect(samePath(tmp, path.join(tmp, 'x'))).toBe(false);
  });

  it('samePath sees through the 8.3 short form of a Windows path that git reports in long form', () => {
    // On Windows os.tmpdir() is typically C:\Users\NAME~1\AppData\Local\Temp. Git answers with the long name.
    const long = fs.realpathSync.native(tmp);
    expect(samePath(tmp, long)).toBe(true);
    expect(samePath(long.replace(/\\/g, '/'), tmp)).toBe(true);
  });
});

describe('workspace', () => {
  const dirLink = (target: string, link: string) => fs.symlinkSync(target, link, process.platform === 'win32' ? 'junction' : 'dir');

  it('finds links, ignoring .git and .codegraph at the top level only', () => {
    const dir = fs.mkdtempSync(path.join(tmp, 'ws-'));
    const outside = fs.mkdtempSync(path.join(tmp, 'outside-'));
    fs.mkdirSync(path.join(dir, 'src', 'deep'), { recursive: true });
    fs.mkdirSync(path.join(dir, '.git'));
    fs.mkdirSync(path.join(dir, '.codegraph'));
    fs.mkdirSync(path.join(dir, 'src', '.git'));
    dirLink(outside, path.join(dir, '.git', 'ignored-link'));
    dirLink(outside, path.join(dir, '.codegraph', 'ignored-link'));
    expect(findSymlinks(dir)).toEqual([]);

    dirLink(outside, path.join(dir, 'src', 'deep', 'escape'));
    dirLink(outside, path.join(dir, 'src', '.git', 'not-top-level'));
    expect(findSymlinks(dir).sort()).toEqual(['src/.git/not-top-level', 'src/deep/escape']);
  });

  it('stops after the limit', () => {
    const dir = fs.mkdtempSync(path.join(tmp, 'ws-'));
    const outside = fs.mkdtempSync(path.join(tmp, 'outside-'));
    for (let i = 0; i < 5; i++) dirLink(outside, path.join(dir, `l${i}`));
    expect(findSymlinks(dir, 3)).toHaveLength(3);
  });

  it('removes a folder with contents, and does nothing when it is already gone', async () => {
    const dir = fs.mkdtempSync(path.join(tmp, 'rm-'));
    fs.mkdirSync(path.join(dir, 'a', 'b'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'a', 'b', 'f.txt'), 'x');
    await removeDir(dir);
    expect(fs.existsSync(dir)).toBe(false);
    await expect(removeDir(dir)).resolves.toBeUndefined();
  });

  it('tells an empty or missing folder from one with content', () => {
    const dir = fs.mkdtempSync(path.join(tmp, 'ne-'));
    expect(isNonEmptyDir(dir)).toBe(false);
    expect(isNonEmptyDir(path.join(dir, 'missing'))).toBe(false);
    fs.writeFileSync(path.join(dir, 'f'), 'x');
    expect(isNonEmptyDir(dir)).toBe(true);
  });
});

describe('commit stamp (decision 6)', () => {
  it('is the checked-out commit after an index, so a CodeGraph upgrade that removes it fails this test', async () => {
    const origin = makeOrigin(tmp, 'origin-stamp', { 'src/a.ts': 'export function alpha() { return 1; }\n' });
    (await lib.CodeGraph.init(origin.dir, { index: true })).close();
    expect(readIndexedCommit(origin.dir)).toBe(origin.head());
  });

  it('is null for a folder with no index, and for an index of a folder that is not a git repo', async () => {
    expect(readIndexedCommit(path.join(tmp, 'nothing-here'))).toBeNull();
    const plain = fs.mkdtempSync(path.join(tmp, 'plain-'));
    fs.writeFileSync(path.join(plain, 'a.ts'), 'export function f() { return 1; }\n');
    (await lib.CodeGraph.init(plain, { index: true })).close();
    expect(readIndexedCommit(plain)).toBeNull();
  });
});

describe('codegraph launcher', () => {
  it('finds the launcher script of the pinned package', () => {
    expect(fs.existsSync(codegraphLauncher())).toBe(true);
  });

  it.each([
    ['Scanning files...', 'scanning'],
    ['Parsing code...', 'parsing'],
    ['Resolving refs...', 'resolving'],
    ['Linking dynamic dispatch...', 'linking'],
    ['*  Indexed 1 files', null],
    ['•  3 nodes, 3 edges in 3.5s', null],
    ['', null],
  ])('reads %j as %s', (line, phase) => {
    expect(phaseOfLine(line)).toBe(phase);
  });
});
