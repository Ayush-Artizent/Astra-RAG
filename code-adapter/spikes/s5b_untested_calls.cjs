// Step 2: calls not yet tested - readOnly open during a write, getCode latency, getCallees,
// getNodesByQualifiedName, and how ambiguous bare names are on Python (Django) and TS.
process.env.CODEGRAPH_TELEMETRY = '0';
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const cgmod = require('@colbymchenry/codegraph');
const CodeGraph = cgmod.CodeGraph || cgmod.default || cgmod;
const ms = (t) => (Number(process.hrtime.bigint() - t) / 1e6).toFixed(1);

async function run(name, project, probes) {
  console.log(`\n===== ${name} =====`);
  const t = process.hrtime.bigint();
  const cg = await CodeGraph.open(project, { readOnly: true });
  console.log('readOnly open ms', ms(t), 'journal', cg.getJournalMode());

  // qualified-name lookup vs searchNodes
  for (const q of probes) {
    const t1 = process.hrtime.bigint();
    const byQ = cg.getNodesByQualifiedName(q);
    const tq = ms(t1);
    const s = cg.searchNodes(q, { limit: 5 });
    console.log(`\n"${q}": getNodesByQualifiedName=${byQ.length} (${tq}ms) searchNodes=${s.length}`);
    for (const x of s.slice(0, 3)) console.log('   ', x.score.toFixed(1), x.node.kind, x.node.qualifiedName, `${x.node.filePath}:${x.node.startLine}`);
    const pick = (byQ[0]) || (s[0] && s[0].node);
    if (pick) {
      const t2 = process.hrtime.bigint();
      const callees = cg.getCallees(pick.id, 1);
      const tc = ms(t2);
      const t3 = process.hrtime.bigint();
      const code = await cg.getCode(pick.id);
      console.log(`    callees=${callees.length} (${tc}ms)  getCode=${code ? code.length + ' chars' : null} (${ms(t3)}ms)`);
    }
  }

  // ambiguity: share of function/method names that occur more than once
  const db = new DatabaseSync(path.join(project, '.codegraph', 'codegraph.db'), { readOnly: true });
  const r = db.prepare(`SELECT COUNT(*) total, SUM(c>1) dup FROM (SELECT name, COUNT(*) c FROM nodes WHERE kind IN ('function','method','class') GROUP BY name)`).get();
  console.log('\ndistinct function/method/class names:', r.total, ' names used by >1 symbol:', r.dup, `(${((r.dup / r.total) * 100).toFixed(0)}%)`);
  const top = db.prepare(`SELECT name, COUNT(*) c FROM nodes WHERE kind IN ('function','method','class') GROUP BY name ORDER BY c DESC LIMIT 5`).all();
  console.log('most duplicated:', top.map((x) => `${x.name} x${x.c}`).join(', '));
  db.close();
  cg.close();
}

(async () => {
  await run('typescript fixture', path.resolve(__dirname, 'fixtures/cg-src'),
    ['CodeGraph::sync', 'CodeGraph.sync', 'sync', 'GraphTraverser::findPath']);
  await run('django (python)', path.resolve(__dirname, 'fixtures/django'),
    ['QuerySet', 'QuerySet.filter', 'QuerySet::filter', 'filter', 'get']);
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
