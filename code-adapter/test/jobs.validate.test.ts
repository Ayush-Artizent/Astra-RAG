import { describe, expect, it } from 'vitest';
import { ProblemError } from '../src/errors.js';
import { scrubText } from '../src/jobs/scrub.js';
import {
  isInternalHost,
  type RepoUrlPolicy,
  requestHash,
  validateIdempotencyKey,
  validateJobRequest,
} from '../src/jobs/validate.js';

const open: RepoUrlPolicy = { allowedRepoHosts: [], allowFileRepos: false };
const SHA = 'a'.repeat(40);

function failure(body: unknown, policy = open): { status: number; code: string; field?: string } | undefined {
  try {
    validateJobRequest(body, policy);
  } catch (e) {
    if (e instanceof ProblemError) return { status: e.status, code: e.errorCode, field: e.field };
    throw e;
  }
  return undefined;
}

describe('bootstrap requests', () => {
  it('accepts the minimal request and the full one', () => {
    expect(validateJobRequest({ type: 'bootstrap', repo_url: 'https://github.com/acme/app' }, open)).toEqual({
      type: 'bootstrap',
      repoUrl: 'https://github.com/acme/app',
      credentialsRef: null,
      branch: null,
    });
    expect(
      validateJobRequest(
        { type: 'bootstrap', repo_url: 'https://gitlab.example.com/a/b.git', credentials_ref: 'acme-prod', branch: 'release/1.2' },
        open,
      ),
    ).toMatchObject({ credentialsRef: 'acme-prod', branch: 'release/1.2' });
  });

  it.each([
    [undefined, 'missing'],
    ['', 'empty'],
    [5, 'not a string'],
    ['not a url', 'not a url'],
    ['http://github.com/a/b', 'http'],
    ['ssh://git@github.com/a/b', 'ssh'],
    ['git://github.com/a/b', 'git protocol'],
    ['/srv/repos/app', 'local path'],
    ['file:///srv/repos/app', 'file url'],
    ['https://user:pw@github.com/a/b', 'credentials in the url'],
    ['https://token@github.com/a/b', 'user name only'],
    ['https://github.com/a/b?token=abc', 'query string'],
    ['https://github.com/a/b#frag', 'fragment'],
    ['https://github.com', 'no path'],
    ['https://github.com/', 'root path'],
    ['https://github.com/a b', 'space'],
    ['https://github.com/a\nb', 'newline'],
    [`https://github.com/${'a'.repeat(2000)}`, 'too long'],
  ])('rejects repo_url %j (%s)', (repo_url, _why) => {
    expect(failure({ type: 'bootstrap', repo_url })).toEqual({ status: 422, code: 'invalid_field', field: 'repo_url' });
  });

  it.each([
    'https://localhost/a/b',
    'https://app.localhost/a/b',
    'https://git.internal/a/b',
    'https://nas.local/a/b',
    'https://127.0.0.1/a/b',
    'https://127.1.2.3/a/b',
    'https://10.0.0.5/a/b',
    'https://172.16.0.1/a/b',
    'https://172.31.255.255/a/b',
    'https://192.168.1.10/a/b',
    'https://169.254.169.254/latest/meta-data',
    'https://100.64.0.1/a/b',
    'https://0.0.0.0/a/b',
    'https://[::1]/a/b',
    'https://[fd00::1]/a/b',
    'https://[fe80::1]/a/b',
    'https://[::ffff:127.0.0.1]/a/b',
    'https://[::ffff:10.0.0.1]/a/b',
    'https://2130706433/a/b', // 127.0.0.1 as one decimal number
    'https://0x7f000001/a/b', // the same in hex
    'https://017700000001/a/b', // the same in octal
  ])('refuses an internal address: %s', (repo_url) => {
    expect(failure({ type: 'bootstrap', repo_url })).toEqual({ status: 422, code: 'invalid_field', field: 'repo_url' });
  });

  it('accepts public addresses, including ones next to private ranges', () => {
    for (const host of ['github.com', '8.8.8.8', '172.15.0.1', '172.32.0.1', '100.63.0.1', '100.128.0.1', '[2606:4700::1111]']) {
      expect(failure({ type: 'bootstrap', repo_url: `https://${host}/a/b` }), host).toBeUndefined();
    }
  });

  it('applies an allow list of hosts, ignoring case', () => {
    const policy = { allowedRepoHosts: ['github.com', 'git.acme.io'], allowFileRepos: false };
    expect(failure({ type: 'bootstrap', repo_url: 'https://GitHub.com/a/b' }, policy)).toBeUndefined();
    expect(failure({ type: 'bootstrap', repo_url: 'https://git.acme.io/a/b' }, policy)).toBeUndefined();
    expect(failure({ type: 'bootstrap', repo_url: 'https://evil.example.com/a/b' }, policy)?.field).toBe('repo_url');
    // A look-alike host is not a match.
    expect(failure({ type: 'bootstrap', repo_url: 'https://github.com.evil.io/a/b' }, policy)?.field).toBe('repo_url');
  });

  it('accepts file:// only when the test-only setting is on', () => {
    const body = { type: 'bootstrap', repo_url: 'file:///tmp/origin' };
    expect(failure(body)).toBeDefined();
    expect(failure(body, { allowedRepoHosts: [], allowFileRepos: true })).toBeUndefined();
  });

  it.each(['has space', 'a/b', '', 'x'.repeat(65), 'semi;colon', '../x', 5])('rejects credentials_ref %j', (credentials_ref) => {
    expect(failure({ type: 'bootstrap', repo_url: 'https://github.com/a/b', credentials_ref })?.field).toBe('credentials_ref');
  });

  it.each(['-x', '--upload-pack=evil', 'a..b', 'a//b', 'x.lock', '/x', 'x/', 'has space', 'a;b', 'a'.repeat(201), '', 5])(
    'rejects branch %j',
    (branch) => {
      expect(failure({ type: 'bootstrap', repo_url: 'https://github.com/a/b', branch })?.field).toBe('branch');
    },
  );

  it.each(['main', 'release/1.2', 'feature/JIRA-12_x', 'v1.0.0'])('accepts branch %s', (branch) => {
    expect(failure({ type: 'bootstrap', repo_url: 'https://github.com/a/b', branch })).toBeUndefined();
  });
});

describe('sync requests', () => {
  it('needs a full commit id and lower-cases it', () => {
    expect(validateJobRequest({ type: 'sync', commit_sha: SHA.toUpperCase() }, open)).toEqual({ type: 'sync', commitSha: SHA });
    expect(validateJobRequest({ type: 'sync', commit_sha: 'b'.repeat(64) }, open)).toMatchObject({ type: 'sync' });
  });

  it.each([undefined, '', 'abc1234', 'a'.repeat(39), 'a'.repeat(41), 'a'.repeat(63), `${'a'.repeat(39)}g`, 5, null, 'main'])(
    'rejects commit_sha %j',
    (commit_sha) => {
      expect(failure({ type: 'sync', commit_sha })).toEqual({ status: 422, code: 'invalid_field', field: 'commit_sha' });
    },
  );
});

describe('fields by type', () => {
  it.each([
    [{ type: 'sync', commit_sha: SHA, repo_url: 'https://github.com/a/b' }, 'repo_url'],
    [{ type: 'sync', commit_sha: SHA, branch: 'main' }, 'branch'],
    [{ type: 'bootstrap', repo_url: 'https://github.com/a/b', commit_sha: SHA }, 'commit_sha'],
    [{ type: 'reconcile', commit_sha: SHA }, 'commit_sha'],
    [{ type: 'bootstrap', repo_url: 'https://github.com/a/b', org_id: 'orgB' }, 'org_id'],
    [{ type: 'sync', commit_sha: SHA, tenant_id: 'x' }, 'tenant_id'],
  ])('%j -> %s is not allowed', (body, field) => {
    expect(failure(body)).toEqual({ status: 422, code: 'invalid_field', field });
  });

  it('accepts a bare reconcile', () => {
    expect(validateJobRequest({ type: 'reconcile' }, open)).toEqual({ type: 'reconcile' });
  });

  it.each([null, undefined, 5, 'x', ['a'], { type: 'purge' }, { type: 5 }, {}])('rejects %j', (body) => {
    expect(failure(body)?.code).toBe('invalid_field');
  });
});

describe('Idempotency-Key', () => {
  it('accepts printable keys and passes through undefined', () => {
    expect(validateIdempotencyKey(undefined)).toBeUndefined();
    expect(validateIdempotencyKey('push-4f2a9c')).toBe('push-4f2a9c');
    expect(validateIdempotencyKey('a'.repeat(128))).toHaveLength(128);
  });

  it.each(['', 'a'.repeat(129), 'has space', 'tab\t', 'new\nline', 'unicodé'])('rejects %j', (key) => {
    expect(() => validateIdempotencyKey(key)).toThrow(ProblemError);
  });
});

describe('requestHash', () => {
  const boot = { type: 'bootstrap' as const, repoUrl: 'https://github.com/a/b', credentialsRef: null, branch: null };

  it('is the same for the same request and differs for any field', () => {
    expect(requestHash(boot)).toBe(requestHash({ ...boot }));
    expect(requestHash(boot)).not.toBe(requestHash({ ...boot, branch: 'main' }));
    expect(requestHash(boot)).not.toBe(requestHash({ ...boot, credentialsRef: 'x' }));
    expect(requestHash(boot)).not.toBe(requestHash({ ...boot, repoUrl: 'https://github.com/a/c' }));
    expect(requestHash({ type: 'sync', commitSha: SHA })).not.toBe(requestHash({ type: 'sync', commitSha: 'b'.repeat(40) }));
    expect(requestHash({ type: 'sync', commitSha: SHA })).not.toBe(requestHash(boot));
  });
});

describe('isInternalHost', () => {
  it('flags loopback, private and link-local, and not public hosts', () => {
    expect(isInternalHost('localhost')).toBe(true);
    expect(isInternalHost('LOCALHOST')).toBe(true);
    expect(isInternalHost('[::1]')).toBe(true);
    expect(isInternalHost('example.com')).toBe(false);
    expect(isInternalHost('1.1.1.1')).toBe(false);
  });
});

describe('scrubText', () => {
  it('removes known secrets, url credentials and authorization headers', () => {
    const text =
      'fatal: could not read from https://oauth2:glpat-SECRET123@gitlab.com/a/b.git\n' +
      'Authorization: Basic eC1hY2Nlc3MtdG9rZW46U0VDUkVU\n' +
      'remote said ghp_TOKENVALUE is invalid';
    const out = scrubText(text, ['ghp_TOKENVALUE']);
    expect(out).not.toContain('glpat-SECRET123');
    expect(out).not.toContain('eC1hY2Nlc3MtdG9rZW46U0VDUkVU');
    expect(out).not.toContain('ghp_TOKENVALUE');
    expect(out).toContain('https://***@gitlab.com/a/b.git');
  });

  it('keeps ordinary text, ignores very short secrets, and cuts long text', () => {
    expect(scrubText('repository not found', ['abc'])).toBe('repository not found');
    const long = scrubText('x'.repeat(5000));
    expect(long.length).toBeLessThan(2100);
    expect(long.endsWith('...')).toBe(true);
  });
});
