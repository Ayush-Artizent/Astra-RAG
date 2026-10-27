import type { Hit, GraphApi, GraphNode } from './modes.js';
import type { NotReadyProject, ReadyProject } from './projects.js';
import { toDisplayName, type Alternative, type ResolveStatus, type Resolution } from './resolve.js';

export type IndexStateOut = 'indexing' | 'complete' | 'partial' | 'failed' | 'not_indexed';
export type PlaneStatus = 'ok' | 'degraded' | 'not_ready';

export interface Snapshot {
  commit_sha: string | null;
  index_time: string | null;
  index_state: IndexStateOut;
}

/**
 * What an answer reflects: the commit, when the index was last built, and the index state.
 * A project that is not ready reports no commit and no time.
 */
export function snapshotOf(p: ReadyProject | NotReadyProject, commitSha: string | null): Snapshot {
  if (!p.ready) {
    return {
      commit_sha: null,
      index_time: null,
      index_state: p.reason === 'not_indexed' ? 'not_indexed' : (p.indexState ?? 'failed'),
    };
  }
  return {
    commit_sha: commitSha,
    index_time: p.lastIndexedAt === null ? null : new Date(p.lastIndexedAt).toISOString(),
    index_state: p.indexState ?? 'complete',
  };
}

export interface ResolvedSymbolOut {
  input: string;
  status: ResolveStatus;
  node_id: string | null;
  qualified_name: string | null;
  alternatives: Alternative[];
}

export interface CodeProvenance {
  file_path: string;
  line_start: number;
  line_end: number;
  symbol: string;
  qualified_name: string;
  node_id: string;
  language?: string;
  commit_sha: string | null;
  index_time: string | null;
}

export interface CodeResult {
  plane_rank: number;
  kind: string;
  score?: number;
  depth?: number;
  relation?: string;
  call_line?: number | null;
  text: string | null;
  provenance: CodeProvenance;
  citation: string;
}

export interface CodeQueryResponse {
  request_id: string;
  plane_status: PlaneStatus;
  snapshot: Snapshot;
  resolved_symbols: ResolvedSymbolOut[];
  results: CodeResult[];
  truncated: boolean;
}

export interface ShapeOptions {
  snapshot: Snapshot;
  includeCode: boolean;
  maxCodeChars: number;
}

/** `src/auth/token.ts:42-67 (TokenService.issue @a1b2c3d)`. The `@sha` part is left out when unknown. */
export function citationOf(node: GraphNode, commitSha: string | null): string {
  const where = `${node.filePath}:${node.startLine}-${node.endLine}`;
  const name = toDisplayName(node.qualifiedName);
  return `${where} (${name}${commitSha ? ` @${commitSha}` : ''})`;
}

export function resolvedSymbolOut(r: Resolution): ResolvedSymbolOut {
  return {
    input: r.input,
    status: r.status,
    node_id: r.best?.id ?? null,
    qualified_name: r.best ? toDisplayName(r.best.qualifiedName) : null,
    alternatives: r.alternatives,
  };
}

async function textOf(g: GraphApi, node: GraphNode, o: ShapeOptions): Promise<string | null> {
  // Whole files are never returned as snippets, and 0 means the caller wants no text.
  if (!o.includeCode || o.maxCodeChars === 0 || node.kind === 'file') return null;
  const code = await g.getCode(node.id);
  if (code === null) return null;
  return code.length > o.maxCodeChars ? code.slice(0, o.maxCodeChars) : code;
}

export async function shapeHits(g: GraphApi, hits: Hit[], o: ShapeOptions): Promise<CodeResult[]> {
  const texts = await Promise.all(hits.map((h) => textOf(g, h.node, o)));
  return hits.map((h, i) => {
    const n = h.node;
    const out: CodeResult = {
      plane_rank: i + 1,
      kind: n.kind,
      text: texts[i] ?? null,
      provenance: {
        file_path: n.filePath,
        line_start: n.startLine,
        line_end: n.endLine,
        symbol: n.name,
        qualified_name: toDisplayName(n.qualifiedName),
        node_id: n.id,
        ...(n.language ? { language: n.language } : {}),
        commit_sha: o.snapshot.commit_sha,
        index_time: o.snapshot.index_time,
      },
      citation: citationOf(n, o.snapshot.commit_sha),
    };
    if (h.score !== undefined) out.score = h.score;
    if (h.depth !== undefined) out.depth = h.depth;
    if (h.relation !== undefined) out.relation = h.relation;
    if (h.callLine !== undefined && h.callLine !== null) out.call_line = h.callLine;
    return out;
  });
}
