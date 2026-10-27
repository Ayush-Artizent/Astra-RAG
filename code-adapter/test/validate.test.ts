import { describe, expect, it } from 'vitest';
import { ProblemError } from '../src/errors.js';
import { validateCodeQuery } from '../src/validate.js';

function failure(body: unknown): { status: number; code: string; field?: string } | undefined {
  try {
    validateCodeQuery(body);
  } catch (e) {
    if (e instanceof ProblemError) return { status: e.status, code: e.errorCode, field: e.field };
    throw e;
  }
  return undefined;
}

describe('contract examples', () => {
  it('accepts the three examples from the OpenAPI file', () => {
    expect(
      validateCodeQuery({
        mode: 'lookup',
        symbols: ['TokenService.issue'],
        keywords: ['token', 'expiry'],
        path_prefix: 'src/auth/',
        limit: 20,
      }),
    ).toMatchObject({ mode: 'lookup', pathPrefix: 'src/auth', limit: 20 });
    expect(
      validateCodeQuery({ mode: 'flow', symbols: ['AuthController.login', 'TokenService.issue'] }),
    ).toMatchObject({ mode: 'flow' });
    expect(validateCodeQuery({ mode: 'callers', symbols: ['TokenService.issue'], depth: 2 })).toMatchObject({
      mode: 'callers',
      depth: 2,
    });
  });
});

describe('defaults', () => {
  it('applies the documented defaults', () => {
    const q = validateCodeQuery({ mode: 'lookup', keywords: ['token'] });
    expect(q).toEqual({
      mode: 'lookup',
      symbols: [],
      keywords: ['token'],
      pathPrefix: null,
      depth: 1,
      limit: 20,
      includeCode: true,
      maxCodeChars: 2000,
      fallbackOrigin: 'structured',
    });
  });

  it('defaults depth to 1 for callers and 3 for impact', () => {
    expect(validateCodeQuery({ mode: 'callers', symbols: ['a'] }).depth).toBe(1);
    expect(validateCodeQuery({ mode: 'impact', symbols: ['a'] }).depth).toBe(3);
  });

  it('accepts and ignores depth for lookup and flow', () => {
    expect(validateCodeQuery({ mode: 'lookup', symbols: ['a'], depth: 4 }).mode).toBe('lookup');
    expect(validateCodeQuery({ mode: 'flow', symbols: ['a', 'b'], depth: 4 }).mode).toBe('flow');
  });

  it('trims symbols and keywords', () => {
    const q = validateCodeQuery({ mode: 'lookup', symbols: ['  A.b  '], keywords: [' k '] });
    expect(q.symbols).toEqual(['A.b']);
    expect(q.keywords).toEqual(['k']);
  });

  it('keeps the order of symbols, which flow mode depends on', () => {
    expect(validateCodeQuery({ mode: 'flow', symbols: ['c', 'a', 'b'] }).symbols).toEqual(['c', 'a', 'b']);
  });
});

describe('mode rules (error_code table)', () => {
  it.each([
    [{ mode: 'lookup' }, 'no_search_terms'],
    [{ mode: 'lookup', symbols: [], keywords: [] }, 'no_search_terms'],
    [{ mode: 'flow', symbols: ['a'] }, 'flow_needs_two_symbols'],
    [{ mode: 'flow' }, 'flow_needs_two_symbols'],
    [{ mode: 'callers', symbols: [] }, 'callers_needs_one_symbol'],
    [{ mode: 'callers', symbols: ['a', 'b'] }, 'callers_needs_one_symbol'],
    [{ mode: 'impact', symbols: [] }, 'impact_needs_one_symbol'],
    [{ mode: 'impact', symbols: ['a', 'b'] }, 'impact_needs_one_symbol'],
  ])('%j -> %s (422)', (body, code) => {
    expect(failure(body)).toMatchObject({ status: 422, code });
  });

  it('accepts the boundary cases', () => {
    expect(failure({ mode: 'lookup', symbols: ['a'] })).toBeUndefined();
    expect(failure({ mode: 'lookup', keywords: ['a'] })).toBeUndefined();
    expect(failure({ mode: 'flow', symbols: ['a', 'b', 'c'] })).toBeUndefined();
    expect(failure({ mode: 'callers', symbols: ['a'] })).toBeUndefined();
    expect(failure({ mode: 'impact', symbols: ['a'] })).toBeUndefined();
  });
});

describe('invalid_field names the offending field', () => {
  it.each([
    [{ mode: 'lookup', symbols: ['a'], bogus: 1 }, 'bogus'],
    [{ mode: 'lookup', symbols: ['a'], tenant_id: 'x' }, 'tenant_id'],
    [{ mode: 'lookup', symbols: ['a'], org_id: 'x' }, 'org_id'],
    [{ symbols: ['a'] }, 'mode'],
    [{ mode: 'explore', symbols: ['a'] }, 'mode'],
    [{ mode: 5, symbols: ['a'] }, 'mode'],
    [{ mode: 'lookup', symbols: 'a' }, 'symbols'],
    [{ mode: 'lookup', symbols: [1] }, 'symbols[0]'],
    [{ mode: 'lookup', symbols: ['a', ''] }, 'symbols[1]'],
    [{ mode: 'lookup', symbols: ['a', '   '] }, 'symbols[1]'],
    [{ mode: 'lookup', symbols: ['x'.repeat(301)] }, 'symbols[0]'],
    [{ mode: 'lookup', symbols: Array.from({ length: 21 }, (_, i) => `s${i}`) }, 'symbols'],
    [{ mode: 'lookup', keywords: ['x'.repeat(101)] }, 'keywords[0]'],
    [{ mode: 'lookup', keywords: Array.from({ length: 21 }, (_, i) => `k${i}`) }, 'keywords'],
    [{ mode: 'callers', symbols: ['a'], depth: 0 }, 'depth'],
    [{ mode: 'callers', symbols: ['a'], depth: 6 }, 'depth'],
    [{ mode: 'callers', symbols: ['a'], depth: 1.5 }, 'depth'],
    [{ mode: 'callers', symbols: ['a'], depth: '2' }, 'depth'],
    [{ mode: 'lookup', symbols: ['a'], limit: 0 }, 'limit'],
    [{ mode: 'lookup', symbols: ['a'], limit: 51 }, 'limit'],
    [{ mode: 'lookup', symbols: ['a'], max_code_chars: -1 }, 'max_code_chars'],
    [{ mode: 'lookup', symbols: ['a'], max_code_chars: 20001 }, 'max_code_chars'],
    [{ mode: 'lookup', symbols: ['a'], include_code: 'yes' }, 'include_code'],
    [{ mode: 'lookup', symbols: ['a'], fallback_origin: 'llm' }, 'fallback_origin'],
    [{ mode: 'lookup', symbols: ['a'], path_prefix: 5 }, 'path_prefix'],
    [{ mode: 'lookup', symbols: ['a'], path_prefix: 'x'.repeat(301) }, 'path_prefix'],
  ])('%j -> invalid_field on %s', (body, field) => {
    expect(failure(body)).toEqual({ status: 422, code: 'invalid_field', field });
  });

  it('rejects a body that is not an object', () => {
    for (const body of [null, undefined, 5, 'x', ['a'], true]) {
      expect(failure(body)).toMatchObject({ status: 422, code: 'invalid_field', field: 'body' });
    }
  });

  it('checks types before the per-mode rules', () => {
    expect(failure({ mode: 'flow', symbols: ['a'], depth: 99 })).toMatchObject({ code: 'invalid_field', field: 'depth' });
  });

  it('accepts the limits exactly', () => {
    expect(
      failure({
        mode: 'lookup',
        symbols: Array.from({ length: 20 }, (_, i) => `s${i}`),
        keywords: ['k'.repeat(100)],
        limit: 50,
        max_code_chars: 20000,
        depth: 5,
      }),
    ).toBeUndefined();
    expect(failure({ mode: 'lookup', symbols: ['x'.repeat(300)], max_code_chars: 0, limit: 1, depth: 1 })).toBeUndefined();
  });
});

describe('path_prefix', () => {
  it('normalises separators and trailing slashes', () => {
    expect(validateCodeQuery({ mode: 'lookup', keywords: ['a'], path_prefix: 'src\\auth\\' }).pathPrefix).toBe('src/auth');
  });

  it('treats an empty or dot prefix as no prefix', () => {
    expect(validateCodeQuery({ mode: 'lookup', keywords: ['a'], path_prefix: '' }).pathPrefix).toBeNull();
    expect(validateCodeQuery({ mode: 'lookup', keywords: ['a'], path_prefix: './' }).pathPrefix).toBeNull();
  });

  it.each(['../x', 'a/../../x', '/etc', 'C:\\x', 'a\0b'])('refuses %j with path_refused', (prefix) => {
    expect(failure({ mode: 'lookup', keywords: ['a'], path_prefix: prefix })).toMatchObject({
      status: 422,
      code: 'path_refused',
    });
  });
});
