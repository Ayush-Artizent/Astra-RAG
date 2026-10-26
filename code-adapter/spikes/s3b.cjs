// S3 follow-up: heuristic edge metadata, and findPath on real call chains.
process.env.CODEGRAPH_TELEMETRY = '0';
const path = require('path');
const { DatabaseSync } = require('node:sqlite');
const cgmod = require('@colbymchenry/codegraph');
const CodeGraph = cgmod.CodeGraph || cgmod.default || cgmod;
const project = path.resolve(__dirname, 'fixtures/cg-src');
const db = new DatabaseSync(path.join(project, '.codegraph', 'codegraph.db'), { readOnly: true });

(async () => {
  const cg = await CodeGraph.open(project);
  const label = (n) => `${n.qualifiedName || n.name} (${n.filePath}:${n.startLine})`;

  console.log('--- heuristic edges (sample of 3)');
  for (const e of db.prepare("SELECT * FROM edges WHERE provenance='heuristic' LIMIT 3").all()) {
    const s = cg.getNode(e.source), t = cg.getNode(e.target);
    console.log({ kind: e.kind, line: e.line, metadata: e.metadata, from: s && label(s), to: t && label(t) });
  }

  console.log('--- distinct metadata keys on heuristic edges');
  const keys = new Set();
  for (const e of db.prepare("SELECT metadata FROM edges WHERE provenance='heuristic' AND metadata IS NOT NULL").all()) {
    try { Object.keys(JSON.parse(e.metadata)).forEach((k) => keys.add(k)); } catch {}
  }
  console.log([...keys]);

  console.log('--- 3-hop calls chain via SQL, then findPath');
  const chain = db.prepare(`
    SELECT a.source s, a.target m, b.target t FROM edges a JOIN edges b ON a.target=b.source
    WHERE a.kind='calls' AND b.kind='calls' AND a.source<>b.target AND a.source<>a.target AND a.target<>b.target LIMIT 1`).get();
  const fp = cg.findPath(chain.s, chain.t, ['calls']);
  console.log('calls-only path', fp && fp.map((h) => ({ n: label(h.node), e: h.edge && { kind: h.edge.kind, prov: h.edge.provenance, line: h.edge.line } })));

  console.log('--- findPath across a heuristic edge');
  const he = db.prepare("SELECT source, target FROM edges WHERE provenance='heuristic' AND kind='calls' LIMIT 1").get();
  const hp = cg.findPath(he.source, he.target, ['calls']);
  console.log('direct heuristic hop followed:', !!hp, hp && hp.map((h) => h.edge && h.edge.provenance));

  console.log('--- findPath with no edge kind filter (what does BFS go through?)');
  const any = cg.findPath(chain.s, chain.t);
  console.log(any && any.map((h) => h.edge && h.edge.kind));

  cg.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
