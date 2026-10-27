// Runs the real resolver against the real Django and TypeScript indexes with hand-labelled inputs.
// Usage: npx tsx spikes/resolver_eval.ts
import '../src/env.js';
import path from 'node:path';
import { createRequire } from 'node:module';
import { resolveSymbol, type SymbolIndex } from '../src/resolve.js';

const lib = createRequire(import.meta.url)('@colbymchenry/codegraph') as {
  CodeGraph: { open(root: string, o: { readOnly: boolean }): Promise<SymbolIndex & { close(): void }> };
};

interface Case { input: string; want: string; status?: string; prefix?: string }

const django: Case[] = [
  { input: 'QuerySet', want: 'QuerySet' },
  { input: 'QuerySet.filter', want: 'QuerySet::filter' },
  { input: 'QuerySet::filter', want: 'QuerySet::filter' },
  { input: 'QuerySet.filter()', want: 'QuerySet::filter' },
  { input: 'django.db.models.QuerySet.filter', want: 'QuerySet::filter' },
  { input: 'django.db.models.query.QuerySet.filter', want: 'QuerySet::filter' },
  { input: 'django/db/models/query.py::QuerySet.filter', want: 'QuerySet::filter' },
  { input: 'query.py::QuerySet.filter', want: 'QuerySet::filter' },
  { input: 'queryset.filter', want: 'QuerySet::filter', status: 'fuzzy' },
  { input: 'Model', want: 'Model' },
  { input: 'Model.save', want: 'Model::save' },
  { input: 'django.db.models.Model.save', want: 'Model::save' },
  { input: 'HttpRequest', want: 'HttpRequest' },
  { input: 'django.http.HttpRequest', want: 'HttpRequest' },
  { input: 'render', want: 'render' }, // the top-level shortcut; 74 methods named render are alternatives
  { input: 'django.shortcuts.render', want: 'render' },
  { input: 'filter', want: '?', status: 'ambiguous' },
  { input: 'filter', want: 'QuerySet::filter', prefix: 'django/db' },
  { input: '__init__', want: '?', status: 'ambiguous' },
  { input: 'Meta', want: '?', status: 'ambiguous' },
  { input: 'get_object_or_404', want: 'get_object_or_404' },
  { input: 'django.shortcuts.get_object_or_404', want: 'get_object_or_404' },
  { input: 'shortcuts.get_object_or_404', want: 'get_object_or_404' },
  { input: 'django.utils.timezone.now', want: 'now' },
  { input: 'reverse', want: 'reverse' },
  { input: 'django.urls.reverse', want: 'reverse' },
  { input: 'QuerySet.filtr', want: '', status: 'not_found' },
  { input: 'NoSuchThing', want: '', status: 'not_found' },
  { input: 'QuerySet.no_such_method', want: '', status: 'not_found' },
  { input: 'Admin', want: '?', status: 'ambiguous' },
  { input: 'ModelAdmin', want: 'ModelAdmin' },
  // Inherited: the method is defined on BaseModelAdmin, so the library has no ModelAdmin::get_queryset.
  { input: 'ModelAdmin.get_queryset', want: '', status: 'not_found' },
  { input: 'BaseModelAdmin.get_queryset', want: 'BaseModelAdmin::get_queryset' },
  { input: 'Q', want: 'Q' },
  { input: 'F', want: 'F' },
];

const ts: Case[] = [
  { input: 'CodeGraph', want: 'CodeGraph' },
  { input: 'CodeGraph.sync', want: 'CodeGraph::sync' },
  { input: 'CodeGraph::sync', want: 'CodeGraph::sync' },
  { input: 'CodeGraph.findPath', want: 'CodeGraph::findPath' },
  { input: 'GraphTraverser.findPath', want: 'GraphTraverser::findPath' },
  { input: 'findPath', want: '?', status: 'ambiguous' },
  { input: 'index.ts::CodeGraph.findPath', want: 'CodeGraph::findPath' },
  // The fixture root is the copied src folder, so file paths here start at `index.ts`, not `src/index.ts`.
  { input: 'src/index.ts::CodeGraph.findPath', want: '', status: 'not_found' },
  { input: 'QueryBuilder', want: 'QueryBuilder' },
  { input: 'QueryBuilder.searchNodes', want: 'QueryBuilder::searchNodes' },
  { input: 'constructor', want: '?', status: 'ambiguous' },
  { input: 'FileWatcher', want: 'FileWatcher' },
  { input: 'codegraph.findpath', want: 'CodeGraph::findPath', status: 'fuzzy' },
  { input: 'CodeGraph.findPaths', want: '', status: 'not_found' },
  { input: 'extract', want: '?', status: 'ambiguous' },
];

async function run(label: string, project: string, cases: Case[]) {
  const cg = await lib.CodeGraph.open(project, { readOnly: true });
  console.log(`\n===== ${label} =====`);
  const tally: Record<string, number> = {};
  let wrong = 0;
  for (const c of cases) {
    const t = process.hrtime.bigint();
    const r = resolveSymbol(cg, c.input, { pathPrefix: c.prefix ?? null });
    const ms = Number(process.hrtime.bigint() - t) / 1e6;
    tally[r.status] = (tally[r.status] ?? 0) + 1;
    const got = r.best?.qualifiedName ?? '';
    const statusOk = c.status ? r.status === c.status : r.status === 'exact';
    const nameOk = c.want === '?' || c.want === '' ? true : got === c.want;
    const ok = statusOk && nameOk;
    if (!ok) wrong++;
    console.log(
      `${ok ? 'ok  ' : 'DIFF'} ${c.input.padEnd(48)} -> ${r.status.padEnd(9)} ${got.padEnd(34)} n=${String(r.totalCandidates).padEnd(4)} ${ms.toFixed(1)}ms  ${r.best?.filePath ?? ''}` +
        (ok ? '' : `   (wanted ${c.status ?? 'exact'} ${c.want})`),
    );
  }
  console.log(`status counts`, tally, `mismatches vs labels: ${wrong}/${cases.length}`);
  cg.close();
}

const spikes = path.resolve(import.meta.dirname);
await run('django (python)', path.join(spikes, 'fixtures/django'), django);
await run('codegraph source (typescript)', path.join(spikes, 'fixtures/cg-src'), ts);
