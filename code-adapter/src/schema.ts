/**
 * Symbol discovery endpoint for code-adapter.
 *
 * GET /internal/v1/code/schema?offset=0&limit=100&kind=function&language=typescript
 *
 * Returns paginated list of all indexed symbols in a project, enabling
 * callers to discover what's available before querying.
 */

import type { CodeGraph } from '@colbymchenry/codegraph';
import type { Node, NodeKind } from '@colbymchenry/codegraph';
import type { GraphApi } from './modes.js';

export interface SchemaSymbol {
  id: string;
  name: string;
  kind: NodeKind;
  file: string;
  language: string;
  line: number;
}

export interface SchemaResponse {
  total: number;
  filtered: number;
  query: {
    offset: number;
    limit: number;
    kind?: string;
    language?: string;
  };
  symbols: {
    total: number;
    count: number;
    items: SchemaSymbol[];
  };
}

interface SchemaParams {
  offset?: string | number;
  limit?: string | number;
  kind?: string;
  language?: string;
}

const DEFAULT_LIMIT = 100;
const MAX_LIMIT = 500;

/**
 * Query schema from a project's CodeGraph
 */
export function querySchema(cg: GraphApi, params: SchemaParams): SchemaResponse {
  const offset = Math.max(0, parseInt(String(params.offset ?? 0), 10));
  const limit = Math.min(MAX_LIMIT, Math.max(1, parseInt(String(params.limit ?? DEFAULT_LIMIT), 10)));

  const kindFilter = params.kind?.trim().toLowerCase();
  const languageFilter = params.language?.trim().toLowerCase();

  // Get stats to know what kinds exist
  const stats = (cg as unknown as CodeGraph).getStats();
  const totalCount = stats.nodeCount;

  // Collect symbols with applied filters
  const symbols: SchemaSymbol[] = [];
  let filtered = 0;

  if (kindFilter) {
    // Query by specific kind
    const nodes = (cg as unknown as CodeGraph).getNodesByKind(kindFilter as NodeKind);
    for (const node of nodes) {
      if (languageFilter && node.language.toLowerCase() !== languageFilter) continue;
      filtered++;
      // Only add to results array if within the requested page
      if (filtered > offset && symbols.length < limit) {
        symbols.push(toSchemaSymbol(node));
      }
    }
  } else {
    // Scan all kinds
    const kindStats = stats.nodesByKind || {};
    const kinds = Object.keys(kindStats) as NodeKind[];

    for (const kind of kinds) {
      const nodes = (cg as unknown as CodeGraph).getNodesByKind(kind);
      for (const node of nodes) {
        if (languageFilter && node.language.toLowerCase() !== languageFilter) continue;
        filtered++;
        // Only add to results array if within the requested page
        if (filtered > offset && symbols.length < limit) {
          symbols.push(toSchemaSymbol(node));
        }
      }
      // Early exit if we've collected enough
      if (symbols.length >= limit && filtered > offset) break;
    }
  }

  return {
    total: totalCount,
    filtered,
    query: {
      offset,
      limit,
      ...(kindFilter && { kind: kindFilter }),
      ...(languageFilter && { language: languageFilter }),
    },
    symbols: {
      total: filtered,
      count: symbols.length,
      items: symbols,
    },
  };
}

function toSchemaSymbol(node: Node): SchemaSymbol {
  return {
    id: node.id,
    name: node.name,
    kind: node.kind,
    file: node.filePath,
    language: node.language,
    line: node.startLine,
  };
}
