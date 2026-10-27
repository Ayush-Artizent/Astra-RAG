/**
 * Symbol resolution: turns a caller's symbol string into a graph node.
 *
 * The library's graph calls take node ids, but callers send names such as `QuerySet.filter`. About 9 to
 * 11 percent of names in the spike repos belong to more than one symbol, so resolution reports how sure it
 * is (`exact`, `fuzzy`, `ambiguous`, `not_found`) and keeps the other candidates. Whether to act on an
 * ambiguous or fuzzy match is decided by the mode, not here.
 */

export interface NodeLike {
  id: string;
  name: string;
  qualifiedName: string;
  kind: string;
  filePath: string;
  startLine: number;
}

/** The slice of the library the resolver needs, so tests can supply a small fake graph. */
export interface SymbolIndex {
  getNodesByQualifiedName(qualifiedName: string): NodeLike[];
  getNodesByName(name: string): NodeLike[];
  getFanIn(ids: readonly string[]): Map<string, number>;
  searchNodes(query: string, options?: { limit?: number }): Array<{ node: NodeLike; score: number }>;
}

export type ResolveStatus = 'exact' | 'fuzzy' | 'ambiguous' | 'not_found';

export interface Alternative {
  qualified_name: string;
  file_path: string;
  line_start: number;
  kind: string;
}

export interface Resolution {
  input: string;
  status: ResolveStatus;
  /** The best candidate. Present for exact, fuzzy and ambiguous. */
  best: NodeLike | null;
  /** All candidates in rank order, best first, capped at MAX_CANDIDATES. */
  candidates: NodeLike[];
  /**
   * How many symbols matched the name before the cap, including nested same-named symbols that were
   * demoted to alternatives. 0 for not_found.
   */
  totalCandidates: number;
  /**
   * Up to 5 other matches (or, for not_found, close names). An `exact` result can have alternatives:
   * a bare name that has one top-level symbol and several same-named methods.
   */
  alternatives: Alternative[];
}

export interface ResolveOptions {
  /** Only consider nodes in files under this relative path. */
  pathPrefix?: string | null;
}

const MAX_ALTERNATIVES = 5;
const MAX_CANDIDATES = 50;
/** Fan-in is a batched query; skip it for names shared by huge numbers of symbols (`__init__`, `Meta`). */
const FAN_IN_LIMIT = 100;

/** Not meaningful targets for callers, impact or flow. */
const EXCLUDED_KINDS = new Set(['file', 'import', 'enum_member', 'parameter']);
/** Callable or type-like kinds. Preferred over properties, constants and variables with the same name. */
const PRIMARY_KINDS = new Set([
  'function', 'method', 'class', 'interface', 'struct', 'trait', 'enum', 'type_alias',
  'protocol', 'module', 'namespace', 'component',
]);

const FILE_EXTENSION = /^[\w.-]+\.(py|ts|tsx|js|jsx|mjs|cjs|java|go|rs|rb|php|cs|kt|swift|c|cc|cpp|h|hpp|scala|dart|lua)$/i;

interface Parsed {
  file: string | null;
  segments: string[];
}

/**
 * `Class.method`, `Class::method`, `Class#method` and `Class.method()` all mean the same.
 * A leading `path/to/file.py::` part restricts the search to that file.
 */
export function parseSymbol(input: string): Parsed {
  let text = input.trim().replace(/\(\s*\)$/, '');
  let file: string | null = null;

  const first = text.indexOf('::');
  if (first > 0) {
    const left = text.slice(0, first).replace(/\\/g, '/');
    if (left.includes('/') || FILE_EXTENSION.test(left)) {
      file = left.replace(/^\.\//, '');
      text = text.slice(first + 2);
    }
  }

  const segments = text
    .replace(/::/g, '.')
    .replace(/#/g, '.')
    .split('.')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  return { file, segments };
}

/** The library's qualified name form for a parsed symbol. */
const toLibraryName = (segments: readonly string[]) => segments.join('::');

/** Output form: the contract uses `.` between segments. */
export const toDisplayName = (qualifiedName: string) => qualifiedName.replace(/::/g, '.');

const inPrefix = (filePath: string, prefix: string) =>
  filePath === prefix || filePath.startsWith(`${prefix}/`);

const inFile = (filePath: string, file: string) => filePath === file || filePath.endsWith(`/${file}`);

/**
 * Whether the leading segments of a dotted path (`django.utils.log`) appear, in order, as directory or
 * file names in `filePath`. Lets `django.utils.log.configure_logging` find a function whose library
 * qualified name is only `configure_logging`.
 *
 * Case sensitive on purpose: module names match their files exactly, while a class name such as
 * `ModelAdmin` must not match a directory called `modeladmin`.
 */
function followsModulePath(filePath: string, modules: readonly string[]): boolean {
  const parts = filePath.replace(/\.[A-Za-z0-9]+$/, '').split('/');
  let at = 0;
  for (const m of modules) {
    const i = parts.indexOf(m, at);
    if (i === -1) return false;
    at = i + 1;
  }
  return true;
}

export function resolveSymbol(index: SymbolIndex, input: string, options: ResolveOptions = {}): Resolution {
  const { file, segments } = parseSymbol(input);
  const prefix = options.pathPrefix ?? null;

  const keep = (nodes: NodeLike[]) =>
    nodes.filter(
      (n) =>
        !EXCLUDED_KINDS.has(n.kind) &&
        (prefix === null || inPrefix(n.filePath, prefix)) &&
        (file === null || inFile(n.filePath, file)),
    );

  /**
   * Type-like nodes (class, function, method...) win over same-named properties or constants, which are
   * kept only as alternatives. More than one node left means ambiguous.
   */
  const settle = (found: NodeLike[], whenSingle: 'exact' | 'fuzzy', others: NodeLike[] = []): Resolution => {
    const primary = found.filter((n) => PRIMARY_KINDS.has(n.kind));
    const pool = primary.length > 0 ? primary : found;
    return finish(index, input, pool.length === 1 ? whenSingle : 'ambiguous', pool, [
      ...found,
      ...rank(index, others),
    ]);
  };

  if (segments.length === 0) return finish(index, input, 'not_found', []);

  // 1. Exact qualified name (`QuerySet::filter`). Not for a single segment: the qualified name `render`
  //    is only the top-level function and would hide every `Widget::render`, so a bare name is matched
  //    against all symbols with that name in step 3.
  if (segments.length >= 2) {
    const exact = keep(index.getNodesByQualifiedName(toLibraryName(segments)));
    if (exact.length > 0) return settle(exact, 'exact');
  }

  // 2. Drop leading segments: `django.db.models.QuerySet.filter` -> `QuerySet.filter`. At least two
  //    segments stay, so a mistyped class name never falls through to every method of that name.
  for (let i = 1; i <= segments.length - 2; i++) {
    const hit = keep(index.getNodesByQualifiedName(toLibraryName(segments.slice(i))));
    if (hit.length > 0) return settle(hit, 'exact');
  }

  // 3. The last segment as a bare name. For a dotted path the leading segments must be a module path
  //    that the candidate's file follows (`django.utils.log.configure_logging`).
  //    A bare name, or `module.name`, means a top-level symbol when one exists: methods and inner classes
  //    are written `Container.name`. Django's tests alone define 234 nested classes called `Model`. The
  //    nested ones are still returned as alternatives.
  const last = segments[segments.length - 1] as string;
  const modules = segments.slice(0, -1);
  let byName = keep(index.getNodesByName(last));
  if (modules.length > 0) byName = byName.filter((n) => followsModulePath(n.filePath, modules));
  if (byName.length > 0) {
    const topLevel = byName.filter((n) => !n.qualifiedName.includes('::'));
    if (topLevel.length > 0) {
      return settle(topLevel, 'exact', byName.filter((n) => n.qualifiedName.includes('::')));
    }
    return settle(byName, 'exact');
  }

  // 4. Search, accepted only when the name matches ignoring case. Plain search ranks `_filter_or_exclude`
  //    above `QuerySet.filter` for the input `QuerySet.filter`, so its ordering is never trusted.
  const hits = keep(index.searchNodes(input.trim(), { limit: 20 }).map((r) => r.node));
  const lowerLast = last.toLowerCase();
  const sameName = hits.filter(
    (n) => n.name.toLowerCase() === lowerLast && (modules.length === 0 || followsQualifier(n, segments)),
  );
  if (sameName.length > 0) return settle(sameName, 'fuzzy');

  // Nothing matched. Offer close names so the caller can correct the input.
  const close = hits.filter((n) => {
    const name = n.name.toLowerCase();
    return name.length >= 3 && (name.includes(lowerLast) || lowerLast.includes(name));
  });
  return finish(index, input, 'not_found', [], close);
}

/** Case-insensitive check that a node's qualified name ends with the caller's segments. */
function followsQualifier(node: NodeLike, segments: readonly string[]): boolean {
  const have = node.qualifiedName.toLowerCase().split('::');
  const want = segments.map((s) => s.toLowerCase());
  if (want.length > have.length) return false;
  return want.every((w, i) => have[have.length - want.length + i] === w);
}

/** Ranks candidates and builds the resolution. `extra` are lower-priority nodes kept as alternatives. */
function finish(
  index: SymbolIndex,
  input: string,
  status: ResolveStatus,
  nodes: NodeLike[],
  extra: NodeLike[] = [],
): Resolution {
  const ranked = rank(index, nodes);
  const total = status === 'not_found' ? 0 : new Set([...ranked, ...extra].map((n) => n.id)).size;
  const candidates = ranked.slice(0, MAX_CANDIDATES);
  const best = candidates[0] ?? null;

  const seen = new Set(best ? [best.id] : []);
  const pool = status === 'not_found' ? extra : [...candidates.slice(1), ...extra];
  const alternatives: Alternative[] = [];
  for (const n of pool) {
    if (seen.has(n.id)) continue;
    seen.add(n.id);
    alternatives.push({
      qualified_name: toDisplayName(n.qualifiedName),
      file_path: n.filePath,
      line_start: n.startLine,
      kind: n.kind,
    });
    if (alternatives.length === MAX_ALTERNATIVES) break;
  }
  return { input, status, best, candidates, totalCandidates: total, alternatives };
}

/**
 * Best first: type-like kinds, then most called, then shortest path, then path and line.
 * "Most called" is only a tie-breaker. In the Django spike it ranks the template-filter `filter` above
 * `QuerySet.filter`, so callers must not treat the best of an ambiguous set as the intended symbol.
 */
function rank(index: SymbolIndex, nodes: NodeLike[]): NodeLike[] {
  if (nodes.length <= 1) return [...nodes];
  const byTier = [...nodes].sort((a, b) => tier(a) - tier(b) || a.filePath.length - b.filePath.length);
  const fanIn =
    byTier.length <= FAN_IN_LIMIT ? index.getFanIn(byTier.map((n) => n.id)) : new Map<string, number>();
  return byTier.sort(
    (a, b) =>
      tier(a) - tier(b) ||
      (fanIn.get(b.id) ?? 0) - (fanIn.get(a.id) ?? 0) ||
      a.filePath.length - b.filePath.length ||
      a.filePath.localeCompare(b.filePath) ||
      a.startLine - b.startLine ||
      a.id.localeCompare(b.id),
  );
}

const tier = (n: NodeLike) => (PRIMARY_KINDS.has(n.kind) ? 0 : 1);
