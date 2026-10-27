import { describe, expect, it, vi } from 'vitest';
import { type NodeLike, type SymbolIndex, parseSymbol, resolveSymbol, toDisplayName } from '../src/resolve.js';

let seq = 0;
function node(qualifiedName: string, kind: string, filePath: string, startLine = 1): NodeLike {
  const name = qualifiedName.split('::').pop() as string;
  return { id: `${kind}:${++seq}`, name, qualifiedName, kind, filePath, startLine };
}

/**
 * A small fake graph modelled on the Django spike: two `filter` methods, a function whose qualified name
 * has no module prefix, a class and constant sharing a name, and a search that ranks badly on purpose.
 */
function fixture(extra: NodeLike[] = [], fanIn: Record<string, number> = {}) {
  const nodes = [
    node('QuerySet', 'class', 'django/db/models/query.py'),
    node('QuerySet::filter', 'method', 'django/db/models/query.py', 1723),
    node('QuerySet::_filter_or_exclude', 'method', 'django/db/models/query.py', 1739),
    node('Library::filter', 'method', 'django/template/library.py', 57),
    node('BaseCustomManager::filter', 'method', 'tests/custom_managers/models.py', 63),
    node('configure_logging', 'function', 'django/utils/log.py', 70),
    node('CodeGraph', 'class', 'src/index.ts', 157),
    node('CodeGraph', 'constant', 'src/worker.ts', 10),
    node('getUserById', 'function', 'src/users.ts', 5),
    node('models.py', 'file', 'django/db/models.py'),
    node('filter', 'import', 'django/db/models/query.py', 3),
    node('render', 'function', 'django/shortcuts.py', 20),
    node('Widget::render', 'method', 'django/forms/widgets.py', 250),
    node('reverse', 'function', 'django/urls/base.py', 30),
    node('URLResolver::reverse', 'method', 'django/urls/resolvers.py', 600),
    node('FilterTests::get_queryset', 'method', 'tests/modeladmin/tests.py', 12),
    ...extra,
  ];
  const fan = (n: NodeLike) =>
    fanIn[n.qualifiedName] ?? ({ 'Library::filter': 68, 'QuerySet::filter': 15, 'BaseCustomManager::filter': 9 } as Record<string, number>)[n.qualifiedName] ?? 0;
  const getFanIn = vi.fn((ids: readonly string[]) => {
    const m = new Map<string, number>();
    for (const id of ids) {
      const n = nodes.find((x) => x.id === id);
      if (n) m.set(id, fan(n));
    }
    return m;
  });
  const index: SymbolIndex = {
    getNodesByQualifiedName: (q) => nodes.filter((n) => n.qualifiedName === q),
    getNodesByName: (name) => nodes.filter((n) => n.name === name),
    getFanIn,
    // Deliberately bad ranking: substring matches in reverse declaration order, so the real symbol is not first.
    searchNodes: (q) =>
      nodes
        .filter((n) => n.qualifiedName.toLowerCase().includes(q.toLowerCase().split('.').pop() as string))
        .reverse()
        .map((n, i) => ({ node: n, score: 100 - i })),
  };
  return { nodes, index, getFanIn };
}

const names = (alts: { qualified_name: string }[]) => alts.map((a) => a.qualified_name);

describe('parseSymbol', () => {
  it('treats ., ::, # and a trailing () as the same separator form', () => {
    for (const s of ['QuerySet.filter', 'QuerySet::filter', 'QuerySet#filter', 'QuerySet.filter()', '  QuerySet.filter  ']) {
      expect(parseSymbol(s)).toEqual({ file: null, segments: ['QuerySet', 'filter'] });
    }
  });

  it('splits a leading file part from the symbol', () => {
    expect(parseSymbol('django/db/models/query.py::QuerySet.filter')).toEqual({
      file: 'django/db/models/query.py',
      segments: ['QuerySet', 'filter'],
    });
    expect(parseSymbol('query.py::QuerySet.filter').file).toBe('query.py');
    expect(parseSymbol('src\\auth\\token.ts::TokenService.issue').file).toBe('src/auth/token.ts');
    expect(parseSymbol('./src/a.ts::f')).toEqual({ file: 'src/a.ts', segments: ['f'] });
  });

  it('does not mistake a qualified name for a file', () => {
    expect(parseSymbol('QuerySet::filter').file).toBeNull();
    expect(parseSymbol('models.Q::filter').file).toBeNull();
  });
});

describe('exact resolution', () => {
  it.each(['QuerySet.filter', 'QuerySet::filter', 'QuerySet#filter', 'QuerySet.filter()'])('%s', (input) => {
    const { index } = fixture();
    const r = resolveSymbol(index, input);
    expect(r.status).toBe('exact');
    expect(r.best?.qualifiedName).toBe('QuerySet::filter');
    expect(r.alternatives).toEqual([]);
  });

  it('drops leading segments of a dotted module path', () => {
    const r = resolveSymbol(fixture().index, 'django.db.models.QuerySet.filter');
    expect(r.status).toBe('exact');
    expect(r.best?.qualifiedName).toBe('QuerySet::filter');
  });

  it('finds a function whose qualified name has no module prefix, by its module path', () => {
    const r = resolveSymbol(fixture().index, 'django.utils.log.configure_logging');
    expect(r.status).toBe('exact');
    expect(r.best?.filePath).toBe('django/utils/log.py');
  });

  it('refuses a module path that does not match the file', () => {
    const r = resolveSymbol(fixture().index, 'django.contrib.auth.configure_logging');
    expect(r.status).toBe('not_found');
    expect(r.best).toBeNull();
  });

  it('prefers the class over a same-named constant, keeping the constant as an alternative', () => {
    const r = resolveSymbol(fixture().index, 'CodeGraph');
    expect(r.status).toBe('exact');
    expect(r.best?.kind).toBe('class');
    expect(r.alternatives).toMatchObject([{ qualified_name: 'CodeGraph', kind: 'constant', file_path: 'src/worker.ts' }]);
  });

  it('reads a bare name as the top-level symbol, and still lists same-named methods', () => {
    const r = resolveSymbol(fixture().index, 'render');
    expect(r.status).toBe('exact');
    expect(r.best?.qualifiedName).toBe('render');
    expect(r.best?.filePath).toBe('django/shortcuts.py');
    expect(r.totalCandidates).toBe(2);
    expect(names(r.alternatives)).toEqual(['Widget.render']);
  });

  it('does not let hundreds of nested same-named classes bury the top-level one', () => {
    // Regression from the Django run: `Model` came back ambiguous with 235 candidates, because the
    // tests define 234 inner classes called `Model`, and the "best" was one of them.
    const nested = Array.from({ length: 120 }, (_, i) => node(`Test${i}::Model`, 'class', `tests/t${i}.py`, i));
    const { index } = fixture([node('Model', 'class', 'django/db/models/base.py', 400), ...nested]);
    const r = resolveSymbol(index, 'Model');
    expect(r.status).toBe('exact');
    expect(r.best?.filePath).toBe('django/db/models/base.py');
    expect(r.totalCandidates).toBe(121);
    expect(r.alternatives).toHaveLength(5);
  });

  it('reports ambiguous when several top-level symbols share the name', () => {
    const { index } = fixture([node('render', 'function', 'django/template/loader.py', 9)]);
    const r = resolveSymbol(index, 'render');
    expect(r.status).toBe('ambiguous');
    expect(r.candidates.every((c) => !c.qualifiedName.includes('::'))).toBe(true);
    expect(names(r.alternatives)).toContain('Widget.render');
  });

  it('reads module.name as the top-level symbol, not a method of the same name', () => {
    const { index } = fixture();
    const shortcut = resolveSymbol(index, 'django.shortcuts.render');
    expect(shortcut.status).toBe('exact');
    expect(shortcut.best?.filePath).toBe('django/shortcuts.py');
    const reverse = resolveSymbol(index, 'django.urls.reverse');
    expect(reverse.status).toBe('exact');
    expect(reverse.best?.qualifiedName).toBe('reverse');
    expect(names(reverse.alternatives)).toEqual(['URLResolver.reverse']);
  });

  it('does not match a class name to a directory with the same letters in other case', () => {
    // Regression from the Django run: `ModelAdmin.get_queryset` matched a test in tests/modeladmin/.
    const r = resolveSymbol(fixture().index, 'ModelAdmin.get_queryset');
    expect(r.status).toBe('not_found');
    expect(r.best).toBeNull();
  });

  it('ignores files and imports as targets', () => {
    const r = resolveSymbol(fixture().index, 'models.py');
    expect(r.best?.kind).not.toBe('file');
  });
});

describe('ambiguity', () => {
  it('reports a bare name shared by several symbols, ranked by how often each is called', () => {
    const r = resolveSymbol(fixture().index, 'filter');
    expect(r.status).toBe('ambiguous');
    expect(r.totalCandidates).toBe(3);
    // Most called first. In the Django spike this is the template-filter `filter`, not `QuerySet.filter`.
    expect(r.best?.qualifiedName).toBe('Library::filter');
    expect(names(r.alternatives)).toEqual(['QuerySet.filter', 'BaseCustomManager.filter']);
  });

  it('lets path_prefix settle the ambiguity', () => {
    const r = resolveSymbol(fixture().index, 'filter', { pathPrefix: 'django/db' });
    expect(r.status).toBe('exact');
    expect(r.best?.qualifiedName).toBe('QuerySet::filter');
  });

  it('does not let a prefix match a sibling directory with the same start', () => {
    const r = resolveSymbol(fixture().index, 'filter', { pathPrefix: 'django/d' });
    expect(r.status).toBe('not_found');
  });

  it('lets a file qualifier settle the ambiguity', () => {
    const { index } = fixture();
    for (const q of ['django/db/models/query.py::filter', 'query.py::QuerySet.filter']) {
      const r = resolveSymbol(index, q);
      expect(r.status).toBe('exact');
      expect(r.best?.qualifiedName).toBe('QuerySet::filter');
    }
    expect(resolveSymbol(index, 'django/template/library.py::filter').best?.qualifiedName).toBe('Library::filter');
    expect(resolveSymbol(index, 'django/other/file.py::filter').status).toBe('not_found');
  });

  it('is deterministic whatever order the graph returns candidates in', () => {
    const a = fixture();
    const b = fixture();
    b.nodes.reverse();
    expect(resolveSymbol(a.index, 'filter').best?.qualifiedName).toBe(resolveSymbol(b.index, 'filter').best?.qualifiedName);
  });

  it('breaks fan-in ties by shorter path, then path text', () => {
    const { index } = fixture(
      [node('A::run', 'method', 'zz/long/path/a.py'), node('B::run', 'method', 'aa/b.py'), node('C::run', 'method', 'ab/c.py')],
      {},
    );
    const r = resolveSymbol(index, 'run');
    expect(r.status).toBe('ambiguous');
    expect(r.candidates.map((c) => c.qualifiedName)).toEqual(['B::run', 'C::run', 'A::run']);
  });

  it('caps candidates and skips the fan-in query for very common names', () => {
    const many = Array.from({ length: 120 }, (_, i) => node(`C${i}::__init__`, 'method', `pkg/m${i}.py`, i));
    const { index, getFanIn } = fixture(many);
    const r = resolveSymbol(index, '__init__');
    expect(r.status).toBe('ambiguous');
    expect(r.totalCandidates).toBe(120);
    expect(r.candidates).toHaveLength(50);
    expect(r.alternatives).toHaveLength(5);
    expect(getFanIn).not.toHaveBeenCalled();
  });
});

describe('fuzzy and not found', () => {
  it('accepts a case-only difference as fuzzy', () => {
    const r = resolveSymbol(fixture().index, 'queryset.FILTER');
    expect(r.status).toBe('fuzzy');
    expect(r.best?.qualifiedName).toBe('QuerySet::filter');
  });

  it('does not accept a misspelling just because search returned something', () => {
    // The fake search puts `QuerySet::_filter_or_exclude` first for this input, as the real one did.
    const r = resolveSymbol(fixture().index, 'QuerySet.filtr');
    expect(r.status).toBe('not_found');
    expect(r.best).toBeNull();
  });

  it('offers close names for a not-found symbol', () => {
    const r = resolveSymbol(fixture().index, 'getUser');
    expect(r.status).toBe('not_found');
    expect(names(r.alternatives)).toContain('getUserById');
  });

  it('returns not_found for empty input', () => {
    for (const s of ['', '   ', '...', '()']) {
      expect(resolveSymbol(fixture().index, s).status).toBe('not_found');
    }
  });

  it('does not fall through from a missing class to every method of that name', () => {
    const r = resolveSymbol(fixture().index, 'Missing.filter');
    expect(r.status).toBe('not_found');
  });
});

describe('toDisplayName', () => {
  it('uses . between segments', () => {
    expect(toDisplayName('QuerySet::filter')).toBe('QuerySet.filter');
    expect(toDisplayName('a::b::c')).toBe('a.b.c');
    expect(toDisplayName('plain')).toBe('plain');
  });
});
