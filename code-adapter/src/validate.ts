import { ProblemError } from './errors.js';
import { safeRelativePrefix } from './paths.js';

export type Mode = 'lookup' | 'flow' | 'callers' | 'impact';
export type FallbackOrigin = 'structured' | 'analyzer';

/** A query request after validation, with defaults applied and paths made safe. */
export interface CodeQuery {
  mode: Mode;
  symbols: string[];
  keywords: string[];
  /** Relative, forward slashes, no trailing slash. Null when the caller gave none. */
  pathPrefix: string | null;
  depth: number;
  limit: number;
  includeCode: boolean;
  maxCodeChars: number;
  fallbackOrigin: FallbackOrigin;
}

const MODES: readonly Mode[] = ['lookup', 'flow', 'callers', 'impact'];
const FALLBACK_ORIGINS: readonly FallbackOrigin[] = ['structured', 'analyzer'];
const KNOWN_FIELDS = new Set([
  'mode',
  'symbols',
  'keywords',
  'path_prefix',
  'depth',
  'limit',
  'include_code',
  'max_code_chars',
  'fallback_origin',
]);

const DEFAULT_DEPTH: Record<Mode, number> = { lookup: 1, flow: 1, callers: 1, impact: 3 };

const invalid = (field: string, detail: string) =>
  new ProblemError(422, 'invalid_field', 'Invalid request', `${field}: ${detail}`, field);

function stringList(body: Record<string, unknown>, field: string, maxItems: number, maxLen: number): string[] {
  const raw = body[field];
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) throw invalid(field, 'must be an array of strings');
  if (raw.length > maxItems) throw invalid(field, `must have at most ${maxItems} items`);
  return raw.map((item, i) => {
    const name = `${field}[${i}]`;
    if (typeof item !== 'string') throw invalid(name, 'must be a string');
    const trimmed = item.trim();
    if (trimmed.length === 0) throw invalid(name, 'must not be empty');
    if (trimmed.length > maxLen) throw invalid(name, `must be at most ${maxLen} characters`);
    return trimmed;
  });
}

function intField(
  body: Record<string, unknown>,
  field: string,
  min: number,
  max: number,
): number | undefined {
  const raw = body[field];
  if (raw === undefined) return undefined;
  if (typeof raw !== 'number' || !Number.isInteger(raw)) throw invalid(field, 'must be an integer');
  if (raw < min || raw > max) throw invalid(field, `must be between ${min} and ${max}`);
  return raw;
}

/**
 * Validates the body of POST /internal/v1/code/query against the contract.
 *
 * Order: shape and types first (`invalid_field`, which names the field), then the per-mode rules
 * (`no_search_terms`, `flow_needs_two_symbols`, `callers_needs_one_symbol`, `impact_needs_one_symbol`).
 */
export function validateCodeQuery(input: unknown): CodeQuery {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    throw invalid('body', 'must be a JSON object');
  }
  const body = input as Record<string, unknown>;

  for (const key of Object.keys(body)) {
    if (!KNOWN_FIELDS.has(key)) throw invalid(key, 'unknown field');
  }

  const mode = body.mode;
  if (typeof mode !== 'string' || !MODES.includes(mode as Mode)) {
    throw invalid('mode', `must be one of ${MODES.join(', ')}`);
  }

  const symbols = stringList(body, 'symbols', 20, 300);
  const keywords = stringList(body, 'keywords', 20, 100);

  let pathPrefix: string | null = null;
  if (body.path_prefix !== undefined) {
    if (typeof body.path_prefix !== 'string') throw invalid('path_prefix', 'must be a string');
    if (body.path_prefix.length > 300) throw invalid('path_prefix', 'must be at most 300 characters');
    const safe = safeRelativePrefix(body.path_prefix);
    pathPrefix = safe === '' ? null : safe;
  }

  const depth = intField(body, 'depth', 1, 5);
  const limit = intField(body, 'limit', 1, 50);
  const maxCodeChars = intField(body, 'max_code_chars', 0, 20000);

  let includeCode = true;
  if (body.include_code !== undefined) {
    if (typeof body.include_code !== 'boolean') throw invalid('include_code', 'must be a boolean');
    includeCode = body.include_code;
  }

  let fallbackOrigin: FallbackOrigin = 'structured';
  if (body.fallback_origin !== undefined) {
    const f = body.fallback_origin;
    if (typeof f !== 'string' || !FALLBACK_ORIGINS.includes(f as FallbackOrigin)) {
      throw invalid('fallback_origin', `must be one of ${FALLBACK_ORIGINS.join(', ')}`);
    }
    fallbackOrigin = f as FallbackOrigin;
  }

  const m = mode as Mode;
  switch (m) {
    case 'lookup':
      if (symbols.length === 0 && keywords.length === 0) {
        throw new ProblemError(422, 'no_search_terms', 'Invalid request', 'lookup needs symbols or keywords');
      }
      break;
    case 'flow':
      if (symbols.length < 2) {
        throw new ProblemError(422, 'flow_needs_two_symbols', 'Invalid request', 'flow needs at least 2 symbols');
      }
      break;
    case 'callers':
      if (symbols.length !== 1) {
        throw new ProblemError(422, 'callers_needs_one_symbol', 'Invalid request', 'callers needs exactly 1 symbol');
      }
      break;
    case 'impact':
      if (symbols.length !== 1) {
        throw new ProblemError(422, 'impact_needs_one_symbol', 'Invalid request', 'impact needs exactly 1 symbol');
      }
      break;
  }

  return {
    mode: m,
    symbols,
    keywords,
    pathPrefix,
    // depth only means something for callers and impact; elsewhere it is accepted and ignored
    depth: depth ?? DEFAULT_DEPTH[m],
    limit: limit ?? 20,
    includeCode,
    maxCodeChars: maxCodeChars ?? 2000,
    fallbackOrigin,
  };
}
