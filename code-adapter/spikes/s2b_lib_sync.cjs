// S2 follow-up: phase timing of a 1-file sync on Django, run through the library (not the CLI).
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const path = require('path');
const cgmod = require('@colbymchenry/codegraph');
const CodeGraph = cgmod.CodeGraph || cgmod.default || cgmod;
const project = path.resolve(__dirname, 'fixtures/django');

(async () => {
  const t0 = Date.now();
  const at = () => ((Date.now() - t0) / 1000).toFixed(1).padStart(6) + 's';
  const target = path.join(project, 'django', 'apps', 'config.py');
  fs.appendFileSync(target, `\ndef spike_lib_${Date.now()}():\n    return 1\n`);

  const cg = await CodeGraph.open(project);
  console.log(at(), 'opened; journal', cg.getJournalMode(), 'rss MB', Math.round(process.memoryUsage().rss / 1048576));
  let last = '';
  const res = await cg.sync({
    onProgress: (p) => {
      const key = p.phase;
      if (key !== last) { console.log(at(), 'phase', p.phase, p.current + '/' + p.total); last = key; }
    },
  });
  console.log(at(), 'sync done', JSON.stringify(res).slice(0, 300));
  console.log(at(), 'rss MB', Math.round(process.memoryUsage().rss / 1048576));
  cg.close();
  console.log(at(), 'closed');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
