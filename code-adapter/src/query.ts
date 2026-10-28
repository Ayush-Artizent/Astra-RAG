import { collectCallers, collectImpact, collectLookup, type Collected, type GraphApi, type Hit } from './modes.js';
import { resolveSymbol, type Resolution } from './resolve.js';
import {
  resolvedSymbolOut,
  shapeHits,
  type CodeQueryResponse,
  type PlaneStatus,
  type Snapshot,
} from './shape.js';
import type { CodeQuery } from './validate.js';

/**
 * What callers, impact and flow do when a symbol name matches several symbols.
 * `refuse` returns no results and the alternatives, so the caller retries with a qualified name.
 * `best` answers for the most-called candidate. In the Django spike that ranked the template filter
 * above `QuerySet.filter`, so `refuse` is the default.
 */
export type AmbiguousPolicy = 'refuse' | 'best';

export interface QueryOptions {
  requestId: string;
  snapshot: Snapshot;
  ambiguousPolicy?: AmbiguousPolicy;
}

const inPrefix = (filePath: string, prefix: string) => filePath === prefix || filePath.startsWith(`${prefix}/`);

/**
 * Runs a validated lookup, callers or impact query against an open project. Flow is not handled here.
 */
export async function runCodeQuery(g: GraphApi, q: CodeQuery, o: QueryOptions): Promise<CodeQueryResponse> {
  const policy = o.ambiguousPolicy ?? 'refuse';
  // For lookup the symbols are the results, so path_prefix narrows which symbol is meant. For callers and
  // impact the prefix restricts where the callers are, and the symbol itself may live anywhere. Use
  // `path/file.py::Class.method` to pin the symbol.
  const symbolPrefix = q.mode === 'lookup' ? q.pathPrefix : null;
  const resolutions: Resolution[] = q.symbols.map((s) => resolveSymbol(g, s, { pathPrefix: symbolPrefix }));

  let found: Collected = { hits: [], capped: false };
  if (q.mode === 'lookup') {
    found = collectLookup(g, { resolutions, keywords: q.keywords, limit: q.limit });
  } else {
    // callers and impact take exactly one symbol (validated).
    const r = resolutions[0] as Resolution;
    const usable = r.best !== null && (r.status !== 'ambiguous' || policy === 'best');
    if (usable) {
      const id = (r.best as { id: string }).id;
      found = q.mode === 'callers' ? collectCallers(g, id, q.depth) : collectImpact(g, id, q.depth);
    }
  }

  let hits: Hit[] = found.hits;
  if (q.pathPrefix !== null) {
    const prefix = q.pathPrefix;
    hits = hits.filter((h) => inPrefix(h.node.filePath, prefix));
  }
  const truncated = found.capped || hits.length > q.limit;
  hits = hits.slice(0, q.limit);

  const results = await shapeHits(g, hits, {
    snapshot: o.snapshot,
    includeCode: q.includeCode,
    maxCodeChars: q.maxCodeChars,
  });

  // Anything short of an exact symbol match, input that came from the fallback analyzer, or a sync in progress
  // (files and index briefly disagree) is low confidence.
  const uncertain =
    resolutions.some((r) => r.status !== 'exact') || q.fallbackOrigin === 'analyzer' || o.snapshot.sync_in_progress;
  const planeStatus: PlaneStatus = uncertain ? 'degraded' : 'ok';

  return {
    request_id: o.requestId,
    plane_status: planeStatus,
    snapshot: o.snapshot,
    resolved_symbols: resolutions.map(resolvedSymbolOut),
    results,
    truncated,
  };
}
