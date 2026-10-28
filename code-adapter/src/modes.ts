import { type NodeLike, type Resolution, type SymbolIndex } from './resolve.js';

export interface GraphNode extends NodeLike {
  endLine: number;
  language?: string;
}

export interface EdgeLike {
  source: string;
  target: string;
  kind: string;
  line?: number;
}

/** Path hop from findPath. */
export interface PathHop {
  /** The node at this hop. */
  node: GraphNode;
  /** The edge that links this node to its predecessor, or null if it's the start node. */
  edge?: EdgeLike | null;
}

/** The slice of CodeGraph the modes need, so tests can drive them with a small fake graph. */
export interface GraphApi extends SymbolIndex {
  getNodesByIds(ids: readonly string[]): Map<string, GraphNode>;
  getIncomingEdgesTo(ids: readonly string[], kinds?: string[]): EdgeLike[];
  getImpactRadius(id: string, depth: number): { nodes: Map<string, GraphNode>; edges: EdgeLike[]; roots: string[] };
  searchNodes(query: string, options?: { limit?: number }): Array<{ node: GraphNode; score: number }>;
  /** Names containing the text, case-insensitive, shortest first: the camelCase infix search FTS cannot do. */
  getNodesByNameSubstring(substring: string, options?: { kinds?: string[]; limit?: number }): GraphNode[];
  getCode(id: string): Promise<string | null>;
  /** Find a path from fromId to toId following only edges of the given kinds, or null if unreachable. */
  findPath(fromId: string, toId: string, kinds?: string[]): PathHop[] | null;
}

/** One result before shaping into the response. */
export interface Hit {
  node: GraphNode;
  /** Distance from the query symbol, for callers and impact. */
  depth?: number;
  /** Edge kind that links this node to the query symbol (calls, imports, ...). */
  relation?: string;
  /** Line of the call site, when the library recorded one. */
  callLine?: number | null;
  score?: number;
}

export interface Collected {
  hits: Hit[];
  /** True when an internal cap stopped the search early. */
  capped: boolean;
}

/** Same edge kinds the library's own getCallers follows. */
export const CALLER_EDGE_KINDS = ['calls', 'references', 'imports', 'instantiates', 'navigates'];
const RELATION_PRIORITY: Record<string, number> = {
  calls: 0,
  instantiates: 1,
  references: 2,
  navigates: 3,
  imports: 4,
};
const relationRank = (kind: string) => RELATION_PRIORITY[kind] ?? 9;

/** Stops a callers or impact search that would otherwise walk a huge graph. */
const MAX_COLLECTED = 1000;

const NOT_TARGETS = new Set(['import', 'enum_member', 'parameter']);

/** Stable order: nearer first, then by file and line. */
export const byDepthThenPlace = (a: Hit, b: Hit) =>
  (a.depth ?? 0) - (b.depth ?? 0) ||
  a.node.filePath.localeCompare(b.node.filePath) ||
  a.node.startLine - b.node.startLine ||
  a.node.id.localeCompare(b.node.id);

/**
 * Callers up to `depth`, breadth first, so every result has its true shortest distance. The library's
 * own getCallers does not report depth, and its depth-first walk can reach a node by a longer route.
 */
export function collectCallers(g: GraphApi, rootId: string, depth: number): Collected {
  const seen = new Set<string>([rootId]);
  let frontier = [rootId];
  const hits: Hit[] = [];
  let capped = false;

  for (let level = 1; level <= depth && frontier.length > 0 && !capped; level++) {
    const edges = g
      .getIncomingEdgesTo(frontier, CALLER_EDGE_KINDS)
      .filter((e) => !seen.has(e.source))
      // For a caller reached by several edges, keep the strongest relation, then the earliest line.
      .sort((a, b) => relationRank(a.kind) - relationRank(b.kind) || (a.line ?? 0) - (b.line ?? 0));

    const firstEdge = new Map<string, EdgeLike>();
    for (const e of edges) if (!firstEdge.has(e.source)) firstEdge.set(e.source, e);

    const nodes = g.getNodesByIds([...firstEdge.keys()]);
    const next: string[] = [];
    for (const [id, edge] of firstEdge) {
      const node = nodes.get(id);
      if (!node) continue;
      seen.add(id);
      next.push(id);
      hits.push({ node, depth: level, relation: edge.kind, callLine: edge.line ?? null });
    }
    frontier = next;
    if (hits.length >= MAX_COLLECTED) capped = true;
  }
  return { hits: hits.sort(byDepthThenPlace), capped };
}

/**
 * Everything that depends on the symbol, up to `depth`. The set comes from the library's
 * getImpactRadius, which also pulls in a class's members. Depths are recomputed from the returned
 * edges: a dependent is one step further out, a contained member is at the same depth as its class.
 */
export function collectImpact(g: GraphApi, rootId: string, depth: number): Collected {
  const sub = g.getImpactRadius(rootId, depth);
  const at = new Map<string, number>([[rootId, 0]]);
  const via = new Map<string, EdgeLike>();

  // Relax until stable. Depths are at most 5, so this takes a handful of passes.
  for (let changed = true; changed; ) {
    changed = false;
    for (const e of sub.edges) {
      if (e.kind === 'contains') {
        const parent = at.get(e.source);
        if (parent !== undefined && (at.get(e.target) ?? Infinity) > parent) {
          at.set(e.target, parent);
          changed = true;
        }
      } else {
        const dependsOn = at.get(e.target);
        if (dependsOn !== undefined && (at.get(e.source) ?? Infinity) > dependsOn + 1) {
          at.set(e.source, dependsOn + 1);
          via.set(e.source, e);
          changed = true;
        }
      }
    }
  }

  const hits: Hit[] = [];
  for (const [id, node] of sub.nodes) {
    const d = at.get(id);
    // Depth 0 is the symbol itself and, for a class, its members: not "affected".
    if (d === undefined || d < 1 || d > depth) continue;
    const edge = via.get(id);
    hits.push({ node, depth: d, relation: edge?.kind, callLine: edge?.line ?? null });
  }
  return { hits: hits.sort(byDepthThenPlace), capped: hits.length >= MAX_COLLECTED };
}

export interface LookupInput {
  resolutions: Resolution[];
  keywords: string[];
  limit: number;
}

/** Candidates kept per ambiguous symbol, so one `__init__` cannot fill the result. */
const AMBIGUOUS_PER_SYMBOL = 10;

/**
 * Lookup: the nodes for each resolved symbol first (every candidate when a name is ambiguous, because
 * recall matters more here), then full-text matches for the keywords.
 */
export function collectLookup(g: GraphApi, input: LookupInput): Collected {
  const hits: Hit[] = [];
  const seen = new Set<string>();
  const add = (hit: Hit) => {
    if (seen.has(hit.node.id) || NOT_TARGETS.has(hit.node.kind)) return;
    seen.add(hit.node.id);
    hits.push(hit);
  };

  for (const r of input.resolutions) {
    const pool = r.status === 'ambiguous' ? r.candidates.slice(0, AMBIGUOUS_PER_SYMBOL) : r.best ? [r.best] : [];
    for (const n of pool) add({ node: n as GraphNode });
  }

  if (input.keywords.length > 0) {
    // Over-fetch: results are filtered by kind and by path prefix afterwards.
    const found = g.searchNodes(input.keywords.join(' '), { limit: Math.max(input.limit * 3, 60) });
    for (const f of found) {
      if (f.node.kind === 'file') continue;
      add({ node: f.node, score: f.score });
    }

    // Full-text search matches the start of a word, so `token` finds `validate_token` but not
    // `issueToken`. Names that merely contain a keyword come after the ranked matches.
    for (const keyword of input.keywords) {
      if (keyword.length < MIN_SUBSTRING_LENGTH) continue;
      for (const node of g.getNodesByNameSubstring(keyword, { kinds: SUBSTRING_KINDS, limit: SUBSTRING_LIMIT })) {
        add({ node });
      }
    }
  }
  return { hits, capped: false };
}

const MIN_SUBSTRING_LENGTH = 3;
const SUBSTRING_LIMIT = 20;
const SUBSTRING_KINDS = ['function', 'method', 'class', 'interface', 'struct', 'trait', 'enum', 'type_alias'];

/**
 * Intermediate representation of a flow hop before shaping into the response.
 */
export interface FlowHopInternal {
  fromNode: GraphNode;
  toNode: GraphNode;
  edge: EdgeLike | null;
}

/**
 * Flow mode: find paths between consecutive symbol pairs using `calls` edges.
 * Chains multiple paths together for 3+ symbols. Returns empty if no path exists.
 */
export function collectFlow(g: GraphApi, symbolIds: string[]): FlowHopInternal[] {
  const result: FlowHopInternal[] = [];

  if (symbolIds.length < 2) return result;

  // For each consecutive pair, find a path
  for (let i = 0; i < symbolIds.length - 1; i++) {
    const fromId = symbolIds[i];
    const toId = symbolIds[i + 1];
    if (fromId === toId) continue;

    const path = g.findPath(fromId, toId, ['calls']);
    if (!path || path.length === 0) {
      // No path found; return empty (graceful degradation)
      return [];
    }

    // Convert PathHop sequence to FlowHopInternal
    for (let j = 0; j < path.length; j++) {
      const hop = path[j];
      if (!hop.node) continue;

      // For the first hop, use the starting node; for subsequent hops, use the previous node
      const fromNode = j === 0 ? hop.node : (path[j - 1]?.node ?? hop.node);
      const toNode = hop.node;

      result.push({
        fromNode,
        toNode,
        edge: hop.edge || null,
      });
    }
  }

  return result;
}
