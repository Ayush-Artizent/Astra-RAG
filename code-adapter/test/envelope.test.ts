import { describe, expect, it } from 'vitest';
import { type Envelope, requireScope, signEnvelope, verifyEnvelope } from '../src/envelope.js';
import { ProblemError } from '../src/errors.js';

const KEY = 'test-key-0123456789abcdef';
const limits = { key: KEY, maxLifetimeSeconds: 300, clockSkewSeconds: 30 };
const NOW = 1_800_000_000;

const make = (over: Partial<Envelope> = {}): Envelope => ({
  org_id: 'orgA',
  project_id: 'p1',
  scopes: ['query'],
  request_id: 'req-1',
  iat: NOW,
  exp: NOW + 120,
  ...over,
});

function codeOf(fn: () => unknown): string | undefined {
  try {
    fn();
  } catch (e) {
    if (e instanceof ProblemError) return `${e.status}:${e.errorCode}`;
    throw e;
  }
  return undefined;
}

describe('verifyEnvelope', () => {
  it('accepts a valid envelope', () => {
    const env = verifyEnvelope(signEnvelope(make(), KEY), limits, NOW + 5);
    expect(env.org_id).toBe('orgA');
    expect(env.project_id).toBe('p1');
  });

  it('rejects a missing header', () => {
    expect(codeOf(() => verifyEnvelope(undefined, limits, NOW))).toBe('401:envelope_invalid');
  });

  it('rejects a malformed header', () => {
    for (const h of ['abc', 'a.b.c', '.', 'x.']) {
      expect(codeOf(() => verifyEnvelope(h, limits, NOW))).toBe('401:envelope_invalid');
    }
  });

  it('rejects a signature made with another key', () => {
    const h = signEnvelope(make(), 'another-key-0123456789abcdef');
    expect(codeOf(() => verifyEnvelope(h, limits, NOW))).toBe('401:envelope_invalid');
  });

  it('rejects a tampered payload (org swapped)', () => {
    const [, sig] = signEnvelope(make(), KEY).split('.');
    const forged = Buffer.from(JSON.stringify(make({ org_id: 'orgB' }))).toString('base64url');
    expect(codeOf(() => verifyEnvelope(`${forged}.${sig}`, limits, NOW))).toBe('401:envelope_invalid');
  });

  it('rejects an expired envelope, allowing 30 s skew', () => {
    const h = signEnvelope(make({ exp: NOW + 60 }), KEY);
    expect(codeOf(() => verifyEnvelope(h, limits, NOW + 60 + 30))).toBeUndefined();
    expect(codeOf(() => verifyEnvelope(h, limits, NOW + 60 + 31))).toBe('401:envelope_expired');
  });

  it('rejects a lifetime over 5 minutes', () => {
    const h = signEnvelope(make({ exp: NOW + 301 }), KEY);
    expect(codeOf(() => verifyEnvelope(h, limits, NOW))).toBe('401:envelope_lifetime_exceeded');
    const ok = signEnvelope(make({ exp: NOW + 300 }), KEY);
    expect(codeOf(() => verifyEnvelope(ok, limits, NOW))).toBeUndefined();
  });

  it('rejects an envelope issued in the future', () => {
    const h = signEnvelope(make({ iat: NOW + 120, exp: NOW + 180 }), KEY);
    expect(codeOf(() => verifyEnvelope(h, limits, NOW))).toBe('401:envelope_invalid');
  });

  it('rejects ids that are not safe directory names', () => {
    for (const bad of ['../x', 'a/b', 'a\\b', '', ' ', 'a'.repeat(65), '.hidden']) {
      const h = signEnvelope(make({ org_id: bad }), KEY);
      expect(codeOf(() => verifyEnvelope(h, limits, NOW))).toBe('401:envelope_invalid');
    }
  });

  it('rejects missing or mistyped fields', () => {
    // correctly signed, but the payload is incomplete
    const signed = signEnvelope({ org_id: 'orgA' } as unknown as Envelope, KEY);
    expect(codeOf(() => verifyEnvelope(signed, limits, NOW))).toBe('401:envelope_invalid');
    // correctly signed, but scopes has the wrong type
    const typed = signEnvelope(make({ scopes: 'query' as unknown as string[] }), KEY);
    expect(codeOf(() => verifyEnvelope(typed, limits, NOW))).toBe('401:envelope_invalid');
  });
});

describe('requireScope', () => {
  it('passes when the scope is present and fails with 403 scope_missing otherwise', () => {
    expect(codeOf(() => requireScope(make({ scopes: ['query'] }), 'query'))).toBeUndefined();
    expect(codeOf(() => requireScope(make({ scopes: ['query'] }), 'code:sync'))).toBe('403:scope_missing');
  });
});
