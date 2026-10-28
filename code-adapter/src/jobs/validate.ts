import { createHash } from 'node:crypto';
import { ProblemError } from '../errors.js';
import type { JobRequest } from './types.js';

export interface RepoUrlPolicy {
  /** Lower-case host names a repo may live on. Empty means any public host. */
  allowedRepoHosts: readonly string[];
  /** Allows `file://` repos. For tests and local development only. */
  allowFileRepos: boolean;
}

const invalid = (field: string, detail: string) =>
  new ProblemError(422, 'invalid_field', 'Invalid request', `${field}: ${detail}`, field);

const TYPES = ['bootstrap', 'sync', 'reconcile'] as const;
const ALLOWED_FIELDS: Record<(typeof TYPES)[number], readonly string[]> = {
  bootstrap: ['type', 'repo_url', 'credentials_ref', 'branch'],
  sync: ['type', 'commit_sha'],
  reconcile: ['type'],
};

const CREDENTIALS_REF = /^[A-Za-z0-9_.-]{1,64}$/;
const BRANCH = /^[A-Za-z0-9][A-Za-z0-9._/-]*$/;
const COMMIT_SHA = /^([0-9a-fA-F]{40}|[0-9a-fA-F]{64})$/;
const IDEMPOTENCY_KEY = /^[\x21-\x7e]{1,128}$/;

/** True for addresses and names that reach this machine or its internal network. */
export function isInternalHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.internal')) {
    return true;
  }
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return (
      a === 0 || a === 10 || a === 127 ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127)
    );
  }
  if (host.includes(':')) {
    if (host === '::1' || host === '::') return true;
    if (/^f[cd][0-9a-f]{2}:/.test(host) || /^fe[89ab][0-9a-f]:/.test(host)) return true;
    const mapped = /^::ffff:(.+)$/.exec(host);
    if (mapped) return isInternalHost(mapped[1] as string);
  }
  return false;
}

function checkRepoUrl(raw: unknown, policy: RepoUrlPolicy): string {
  if (typeof raw !== 'string' || raw.length === 0) throw invalid('repo_url', 'is required for bootstrap');
  if (raw.length > 2000) throw invalid('repo_url', 'must be at most 2000 characters');
  if (/[\s\x00-\x1f\x7f]/.test(raw)) throw invalid('repo_url', 'must not contain spaces or control characters');
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw invalid('repo_url', 'must be a valid URL');
  }
  if (url.protocol === 'file:') {
    if (!policy.allowFileRepos) throw invalid('repo_url', 'must use https');
    return url.href;
  }
  if (url.protocol !== 'https:') throw invalid('repo_url', 'must use https');
  if (url.username !== '' || url.password !== '') throw invalid('repo_url', 'must not contain credentials; use credentials_ref');
  if (url.search !== '' || url.hash !== '') throw invalid('repo_url', 'must not contain a query string or fragment');
  if (url.pathname === '' || url.pathname === '/') throw invalid('repo_url', 'must include a repository path');
  if (isInternalHost(url.hostname)) throw invalid('repo_url', 'must not point at a loopback or private address');
  if (policy.allowedRepoHosts.length > 0 && !policy.allowedRepoHosts.includes(url.hostname.toLowerCase())) {
    throw invalid('repo_url', 'host is not allowed');
  }
  return url.href;
}

function optionalString(body: Record<string, unknown>, field: string): string | undefined {
  const v = body[field];
  if (v === undefined) return undefined;
  if (typeof v !== 'string') throw invalid(field, 'must be a string');
  return v;
}

/** Validates the body of POST /internal/v1/code/jobs. Which fields are allowed depends on `type`. */
export function validateJobRequest(input: unknown, policy: RepoUrlPolicy): JobRequest {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    throw invalid('body', 'must be a JSON object');
  }
  const body = input as Record<string, unknown>;
  const type = body.type;
  if (typeof type !== 'string' || !(TYPES as readonly string[]).includes(type)) {
    throw invalid('type', `must be one of ${TYPES.join(', ')}`);
  }
  const t = type as (typeof TYPES)[number];
  for (const key of Object.keys(body)) {
    if (!ALLOWED_FIELDS[t].includes(key)) throw invalid(key, `is not allowed for ${t}`);
  }

  if (t === 'reconcile') return { type: 'reconcile' };

  if (t === 'sync') {
    const sha = body.commit_sha;
    if (typeof sha !== 'string' || !COMMIT_SHA.test(sha)) {
      throw invalid('commit_sha', 'is required and must be a full 40 or 64 character commit id');
    }
    return { type: 'sync', commitSha: sha.toLowerCase() };
  }

  const repoUrl = checkRepoUrl(body.repo_url, policy);

  const credentialsRef = optionalString(body, 'credentials_ref');
  if (credentialsRef !== undefined && !CREDENTIALS_REF.test(credentialsRef)) {
    throw invalid('credentials_ref', 'must be 1 to 64 letters, digits, dots, dashes or underscores');
  }

  const branch = optionalString(body, 'branch');
  if (branch !== undefined) {
    if (branch.length > 200 || !BRANCH.test(branch) || branch.includes('..') || branch.includes('//') || branch.endsWith('/') || branch.endsWith('.lock')) {
      throw invalid('branch', 'is not a valid branch name');
    }
  }
  return { type: 'bootstrap', repoUrl, credentialsRef: credentialsRef ?? null, branch: branch ?? null };
}

export function validateIdempotencyKey(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  if (!IDEMPOTENCY_KEY.test(value)) throw invalid('Idempotency-Key', 'must be 1 to 128 printable characters');
  return value;
}

/** Same request, same hash. Used to tell an idempotent replay from a reused key. */
export function requestHash(req: JobRequest): string {
  const canonical =
    req.type === 'bootstrap'
      ? { type: req.type, repoUrl: req.repoUrl, credentialsRef: req.credentialsRef, branch: req.branch }
      : req.type === 'sync'
        ? { type: req.type, commitSha: req.commitSha }
        : { type: req.type };
  return createHash('sha256').update(JSON.stringify(canonical)).digest('hex');
}
