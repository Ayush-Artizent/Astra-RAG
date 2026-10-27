import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import '../src/env.js';
import { type SymbolIndex, resolveSymbol } from '../src/resolve.js';

// Real CodeGraph on a tiny repo, so a change in the library's qualified-name format fails here.
const lib = createRequire(import.meta.url)('@colbymchenry/codegraph') as {
  CodeGraph: {
    init(root: string, o: { index: boolean }): Promise<{ close(): void }>;
    open(root: string, o: { readOnly: boolean }): Promise<SymbolIndex & { close(): void }>;
  };
};

let dir: string;
let cg: SymbolIndex & { close(): void };

const FILES: Record<string, string> = {
  'web/views.ts': [
    'export function render(page: string) { return page; }',
    'export class Widget { render() { return 1; } }',
    'export class Panel { render() { return 2; } }',
    '',
  ].join('\n'),
  'pkg/util.py': [
    'def helper():',
    '    return 1',
    '',
    'class Outer:',
    '    class Inner:',
    '        def go(self):',
    '            return 2',
    '',
    '    def run(self):',
    '        return helper()',
    '',
  ].join('\n'),
};

beforeAll(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-resolve-'));
  for (const [rel, text] of Object.entries(FILES)) {
    const file = path.join(dir, rel);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
  }
  (await lib.CodeGraph.init(dir, { index: true })).close();
  cg = await lib.CodeGraph.open(dir, { readOnly: true });
}, 120_000);

afterAll(() => {
  cg?.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('resolveSymbol on a real index', () => {
  it('resolves Class.method in both dotted and :: form', () => {
    for (const s of ['Widget.render', 'Widget::render', 'Widget#render', 'Widget.render()']) {
      const r = resolveSymbol(cg, s);
      expect(r.status, s).toBe('exact');
      expect(r.best?.qualifiedName).toBe('Widget::render');
      expect(r.best?.filePath).toBe('web/views.ts');
    }
  });

  it('reads a bare name as the top-level function and lists the methods as alternatives', () => {
    const r = resolveSymbol(cg, 'render');
    expect(r.status).toBe('exact');
    expect(r.best?.qualifiedName).toBe('render');
    expect(r.alternatives.map((a) => a.qualified_name).sort()).toEqual(['Panel.render', 'Widget.render']);
    expect(r.totalCandidates).toBe(3);
  });

  it('resolves a unique method by its bare name, and honours path_prefix', () => {
    expect(resolveSymbol(cg, 'run').status).toBe('exact');
    expect(resolveSymbol(cg, 'render', { pathPrefix: 'web' }).status).toBe('exact');
    expect(resolveSymbol(cg, 'render', { pathPrefix: 'pkg' }).status).toBe('not_found');
  });

  it('resolves Python names, nested classes and module paths', () => {
    expect(resolveSymbol(cg, 'helper').best?.filePath).toBe('pkg/util.py');
    expect(resolveSymbol(cg, 'pkg.util.helper').status).toBe('exact');
    expect(resolveSymbol(cg, 'Outer.run').best?.qualifiedName).toBe('Outer::run');
    const inner = resolveSymbol(cg, 'Outer.Inner.go');
    expect(inner.status).toBe('exact');
    expect(inner.best?.qualifiedName).toBe('Outer::Inner::go');
  });

  it('accepts a file qualifier and refuses a wrong one', () => {
    expect(resolveSymbol(cg, 'views.ts::Panel.render').best?.qualifiedName).toBe('Panel::render');
    expect(resolveSymbol(cg, 'pkg/util.py::Widget.render').status).toBe('not_found');
  });

  it('does not accept a near miss as a match', () => {
    expect(resolveSymbol(cg, 'Widget.rendr').status).toBe('not_found');
    expect(resolveSymbol(cg, 'Gadget.render').status).toBe('not_found');
    expect(resolveSymbol(cg, 'widget.RENDER').status).toBe('fuzzy');
  });
});
