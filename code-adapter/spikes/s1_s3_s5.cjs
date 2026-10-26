// Spike S1 (WAL, Node 24), S3 (findPath edge metadata), S5 (name resolution).
process.env.CODEGRAPH_TELEMETRY = '0';
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const cgmod = require('@colbymchenry/codegraph');
const CodeGraph = cgmod.CodeGraph || cgmod.default || cgmod;

const project = path.resolve(__dirname, process.argv[2] || 'fixtures/cg-src');

(async () => {
  console.log('node', process.version);

  // S1: WAL probe on a scratch db, then on the real index
  const scratch = new DatabaseSync(':memory:');
  console.log('scratch journal_mode', scratch.prepare('PRAGMA journal_mode').get());
  const real = new DatabaseSync(path.join(project, '.codegraph', 'codegraph.db'), { readOnly: true });
  console.log('real journal_mode', real.prepare('PRAGMA journal_mode').get());
  real.close();

  const cg = await CodeGraph.open(project);
  console.log('stats', JSON.stringify(cg.getStats()).slice(0, 300));

  // S5: name resolution behaviour
  for (const q of ['CodeGraph', 'findPath', 'CodeGraph.findPath', 'getCallers', 'sync', 'QueryBuilder']) {
    const r = cg.searchNodes(q, { limit: 5 });
    console.log(`\nsearch "${q}" -> ${r.length}`);
    for (const x of r) {
      console.log(' ', x.score.toFixed(2), x.node.kind, x.node.qualifiedName || x.node.name, `${x.node.filePath}:${x.node.startLine}-${x.node.endLine}`);
    }
  }

  // S3: findPath edge metadata
  const a = cg.searchNodes('indexAll', { limit: 3 }).find((x) => x.node.kind === 'method');
  const b = cg.searchNodes('searchNodes', { limit: 5 }).find((x) => x.node.kind === 'method');
  console.log('\nfrom', a && a.node.qualifiedName, 'to', b && b.node.qualifiedName);
  const p = a && b ? cg.findPath(a.node.id, b.node.id) : null;
  console.log('path', p ? p.length + ' hops' : p);
  if (p) for (const h of p) console.log(' ', h.node.qualifiedName || h.node.name, '<-', h.edge ? JSON.stringify({ kind: h.edge.kind, provenance: h.edge.provenance, line: h.edge.line, metadata: h.edge.metadata }) : null);

  // edge provenance distribution
  const rows = new DatabaseSync(path.join(project, '.codegraph', 'codegraph.db'), { readOnly: true })
    .prepare('SELECT provenance, kind, COUNT(*) c FROM edges GROUP BY provenance, kind ORDER BY c DESC LIMIT 12').all();
  console.log('\nedge provenance/kind counts', rows);

  cg.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
