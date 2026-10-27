// Real library output for the example requests in the resolver walkthrough (Django fixture).
process.env.CODEGRAPH_TELEMETRY = '0';
const path = require('path');
const { CodeGraph } = require('@colbymchenry/codegraph');
const project = path.resolve(__dirname, 'fixtures/django');
const loc = (n) => `${n.filePath}:${n.startLine}-${n.endLine}`;
const row = (n) => ({ qn: n.qualifiedName, kind: n.kind, loc: loc(n), id: n.id.slice(0, 12) });

(async () => {
  const cg = await CodeGraph.open(project, { readOnly: true });
  console.log('lastIndexedAt', new Date(cg.getLastIndexedAt()).toISOString(), 'state', cg.getIndexState());

  console.log('\n[1] exact: getNodesByQualifiedName("QuerySet::filter")');
  const qf = cg.getNodesByQualifiedName('QuerySet::filter');
  console.log(qf.map(row));

  console.log('\n[2] callers of QuerySet::filter, depth 1 (first 4 of N)');
  const callers = cg.getCallers(qf[0].id, 1);
  console.log('total', callers.length, callers.slice(0, 4).map((c) => ({ ...row(c.node), line: c.edge.line, prov: c.edge.provenance })));

  console.log('\n[3] bare name "filter": getNodesByName');
  const f = cg.getNodesByName('filter').filter((n) => ['method', 'function', 'class'].includes(n.kind));
  const fanIn = cg.getFanIn(f.map((n) => n.id));
  console.log('candidates', f.length);
  console.log(f.map((n) => ({ ...row(n), fanIn: fanIn.get(n.id) || 0 })).sort((a, b) => b.fanIn - a.fanIn).slice(0, 5));

  console.log('\n[4] not found: getNodesByQualifiedName("QuerySet::filtr") + searchNodes("QuerySet.filtr")');
  console.log(cg.getNodesByQualifiedName('QuerySet::filtr').length, cg.searchNodes('QuerySet.filtr', { limit: 3 }).map((r) => row(r.node)));

  console.log('\n[5] flow: QuerySet::filter -> QuerySet::_filter_or_exclude (calls only)');
  const a = qf[0];
  const b = cg.getNodesByQualifiedName('QuerySet::_filter_or_exclude')[0];
  const p = cg.findPath(a.id, b.id, ['calls']);
  console.log(p && p.map((h) => ({ ...row(h.node), via: h.edge && { kind: h.edge.kind, prov: h.edge.provenance, line: h.edge.line } })));

  console.log('\n[6] impact of QuerySet::_filter_or_exclude depth 1');
  const sub = cg.getImpactRadius(b.id, 1);
  console.log('nodes', sub.nodes.size, 'edges', sub.edges.length, 'keys', Object.keys(sub));
  const sample = [...sub.nodes.values()].slice(0, 3).map(row);
  console.log(sample);

  console.log('\n[7] getCode snippet (first 160 chars) for QuerySet::filter');
  console.log(JSON.stringify((await cg.getCode(a.id)).slice(0, 160)));
  cg.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
