import { describe, expect, it } from 'vitest';
import {
  collectCallers,
  collectImpact,
  collectLookup,
  type EdgeLike,
  type GraphApi,
  type GraphNode,
} from '../src/modes.js';
import type { Resolution } from '../src/resolve.js';
import { citationOf } from '../src/shape.js';

const mk = (id: string, kind = 'function', filePath = `src/${id}.ts`, line = 1): GraphNode => ({
  id,
  name: id,
  qualifiedName: id,
  kind,
  filePath,
  startLine: line,
  endLine: line + 5,
});

/** A fake graph over explicit nodes and edges (source -> target). */
function graph(
  nodes: GraphNode[],
  edges: EdgeLike[],
  search: Array<{ node: GraphNode; score: number }> = [],
  substring: GraphNode[] = [],
) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const g: GraphApi = {
    getNodesByQualifiedName: () => [],
    getNodesByName: () => [],
    getFanIn: () => new Map(),
    searchNodes: () => search,
    getNodesByNameSubstring: (text) => substring.filter((n) => n.name.toLowerCase().includes(text.toLowerCase())),
    getNodesByIds: (ids) => new Map(ids.flatMap((i) => (byId.has(i) ? [[i, byId.get(i)!] as const] : []))),
    getIncomingEdgesTo: (ids, kinds) =>
      edges.filter((e) => ids.includes(e.target) && (!kinds || kinds.includes(e.kind))),
    getImpactRadius: (rootId, depth) => {
      // Mirrors the library: dependents by incoming non-contains edges, plus a container's members.
      const out = new Map<string, GraphNode>([[rootId, byId.get(rootId)!]]);
      const got: EdgeLike[] = [];
      const walk = (id: string, d: number) => {
        for (const e of edges.filter((x) => x.source === id && x.kind === 'contains')) {
          if (!out.has(e.target)) {
            out.set(e.target, byId.get(e.target)!);
            got.push(e);
            walk(e.target, d);
          }
        }
        if (d >= depth) return;
        for (const e of edges.filter((x) => x.target === id && x.kind !== 'contains')) {
          got.push(e);
          if (!out.has(e.source)) {
            out.set(e.source, byId.get(e.source)!);
            walk(e.source, d + 1);
          }
        }
      };
      walk(rootId, 0);
      return { nodes: out, edges: got, roots: [rootId] };
    },
    getCode: async () => null,
  };
  return g;
}

const call = (source: string, target: string, line = 1, kind = 'calls'): EdgeLike => ({ source, target, kind, line });

describe('collectCallers', () => {
  const nodes = ['root', 'a', 'b', 'c', 'd'].map((id) => mk(id));

  it('returns direct callers at depth 1 with the call-site line', () => {
    const g = graph(nodes, [call('a', 'root', 10), call('b', 'root', 20), call('c', 'a')]);
    const r = collectCallers(g, 'root', 1);
    expect(r.hits.map((h) => h.node.id)).toEqual(['a', 'b']);
    expect(r.hits.map((h) => [h.depth, h.relation, h.callLine])).toEqual([
      [1, 'calls', 10],
      [1, 'calls', 20],
    ]);
  });

  it('walks outward level by level and reports each caller at its shortest distance', () => {
    // d calls root directly and also through a: the shortest distance is 1, not 2.
    const g = graph(nodes, [call('a', 'root'), call('d', 'a'), call('d', 'root'), call('c', 'd')]);
    const r = collectCallers(g, 'root', 5);
    const depthOf = Object.fromEntries(r.hits.map((h) => [h.node.id, h.depth]));
    expect(depthOf).toEqual({ a: 1, d: 1, c: 2 });
  });

  it('stops at the requested depth', () => {
    const g = graph(nodes, [call('a', 'root'), call('b', 'a'), call('c', 'b')]);
    expect(collectCallers(g, 'root', 2).hits.map((h) => h.node.id)).toEqual(['a', 'b']);
    expect(collectCallers(g, 'root', 3).hits.map((h) => h.node.id)).toEqual(['a', 'b', 'c']);
  });

  it('handles recursion and cycles without repeating anything', () => {
    const g = graph(nodes, [call('root', 'root'), call('a', 'root'), call('root', 'a'), call('b', 'a'), call('a', 'b')]);
    const r = collectCallers(g, 'root', 5);
    expect(r.hits.map((h) => h.node.id).sort()).toEqual(['a', 'b']);
  });

  it('keeps the strongest relation when a caller is reached by several edges', () => {
    const g = graph(nodes, [call('a', 'root', 1, 'imports'), call('a', 'root', 9, 'references'), call('a', 'root', 30, 'calls')]);
    const [hit] = collectCallers(g, 'root', 1).hits;
    expect(hit).toMatchObject({ relation: 'calls', callLine: 30 });
  });

  it('ignores edge kinds that are not callers', () => {
    const g = graph(nodes, [call('a', 'root', 1, 'extends'), call('b', 'root', 1, 'contains')]);
    expect(collectCallers(g, 'root', 1).hits).toEqual([]);
  });

  it('returns nothing for a symbol nobody calls', () => {
    expect(collectCallers(graph(nodes, []), 'root', 3)).toEqual({ hits: [], capped: false });
  });

  it('orders by depth, then file, then line', () => {
    const ns = [mk('root'), mk('x', 'function', 'b.ts', 5), mk('y', 'function', 'a.ts', 9), mk('z', 'function', 'a.ts', 2), mk('w', 'function', 'a.ts', 1)];
    const g = graph(ns, [call('x', 'root'), call('y', 'root'), call('z', 'root'), call('w', 'z')]);
    expect(collectCallers(g, 'root', 2).hits.map((h) => h.node.id)).toEqual(['z', 'y', 'x', 'w']);
  });

  it('caps a huge fan-in and says so', () => {
    const many = Array.from({ length: 1200 }, (_, i) => mk(`n${i}`));
    const g = graph([mk('root'), ...many], many.map((n) => call(n.id, 'root')));
    const r = collectCallers(g, 'root', 1);
    expect(r.capped).toBe(true);
    expect(r.hits.length).toBe(1200); // a level is finished before the cap stops the next one
    const deeper = collectCallers(g, 'root', 3);
    expect(deeper.capped).toBe(true);
  });
});

describe('collectImpact', () => {
  it('reports dependents with their depth, excluding the symbol itself', () => {
    const ns = ['root', 'a', 'b', 'c'].map((id) => mk(id));
    const g = graph(ns, [call('a', 'root'), call('b', 'a'), call('c', 'b')]);
    const r = collectImpact(g, 'root', 2);
    expect(r.hits.map((h) => [h.node.id, h.depth])).toEqual([['a', 1], ['b', 2]]);
  });

  it('treats a class member as part of the class, so its callers are depth 1', () => {
    const ns = [mk('Cls', 'class'), mk('Cls.m', 'method'), mk('user')];
    const g = graph(ns, [{ source: 'Cls', target: 'Cls.m', kind: 'contains' }, call('user', 'Cls.m')]);
    const r = collectImpact(g, 'Cls', 3);
    expect(r.hits.map((h) => [h.node.id, h.depth])).toEqual([['user', 1]]);
  });

  it('uses the shortest path when a dependent is reachable two ways', () => {
    const ns = ['root', 'a', 'b'].map((id) => mk(id));
    const g = graph(ns, [call('a', 'root'), call('b', 'a'), call('b', 'root')]);
    const r = collectImpact(g, 'root', 3);
    expect(Object.fromEntries(r.hits.map((h) => [h.node.id, h.depth]))).toEqual({ a: 1, b: 1 });
  });

  it('returns nothing when no one depends on the symbol', () => {
    expect(collectImpact(graph([mk('root')], []), 'root', 3).hits).toEqual([]);
  });
});

describe('collectLookup', () => {
  const resolution = (status: Resolution['status'], nodes: GraphNode[]): Resolution => ({
    input: 'x',
    status,
    best: nodes[0] ?? null,
    candidates: nodes,
    totalCandidates: nodes.length,
    alternatives: [],
  });

  it('puts resolved symbols first, then keyword matches, without duplicates', () => {
    const sym = mk('sym');
    const kw1 = mk('kw1');
    const g = graph([], [], [{ node: kw1, score: 9 }, { node: sym, score: 8 }]);
    const r = collectLookup(g, { resolutions: [resolution('exact', [sym])], keywords: ['k'], limit: 10 });
    expect(r.hits.map((h) => h.node.id)).toEqual(['sym', 'kw1']);
    expect(r.hits[1]?.score).toBe(9);
  });

  it('returns every candidate of an ambiguous symbol, capped at 10', () => {
    const many = Array.from({ length: 25 }, (_, i) => mk(`c${i}`));
    const r = collectLookup(graph([], []), { resolutions: [resolution('ambiguous', many)], keywords: [], limit: 50 });
    expect(r.hits).toHaveLength(10);
  });

  it('adds names that only contain the keyword (camelCase), after the ranked matches, without duplicates', () => {
    const ranked = mk('validate_token');
    const infix = [mk('issueToken'), mk('validate_token'), mk('expireToken')];
    const g = graph([], [], [{ node: ranked, score: 33 }], infix);
    const r = collectLookup(g, { resolutions: [], keywords: ['token'], limit: 10 });
    expect(r.hits.map((h) => h.node.id)).toEqual(['validate_token', 'issueToken', 'expireToken']);
    expect(r.hits[0]?.score).toBe(33);
    expect(r.hits[1]?.score).toBeUndefined();
  });

  it('does not run the substring search for very short keywords', () => {
    const g = graph([], [], [], [mk('aValue'), mk('bag')]);
    const r = collectLookup(g, { resolutions: [], keywords: ['a', 'ag'], limit: 10 });
    expect(r.hits).toEqual([]);
  });

  it('skips files and imports in keyword results and contributes nothing for an unknown symbol', () => {
    const g = graph([], [], [{ node: mk('f', 'file'), score: 1 }, { node: mk('i', 'import'), score: 1 }, { node: mk('ok'), score: 1 }]);
    const r = collectLookup(g, { resolutions: [resolution('not_found', [])], keywords: ['k'], limit: 10 });
    expect(r.hits.map((h) => h.node.id)).toEqual(['ok']);
  });
});

describe('citationOf', () => {
  it('formats path, lines, dotted name and commit', () => {
    const n = { ...mk('x'), qualifiedName: 'TokenService::issue', filePath: 'src/auth/token.ts', startLine: 42, endLine: 67 };
    expect(citationOf(n, 'a1b2c3d')).toBe('src/auth/token.ts:42-67 (TokenService.issue @a1b2c3d)');
  });

  it('leaves out the commit when it is unknown', () => {
    const n = { ...mk('x'), qualifiedName: 'f', filePath: 'a.py', startLine: 1, endLine: 3 };
    expect(citationOf(n, null)).toBe('a.py:1-3 (f)');
  });
});
