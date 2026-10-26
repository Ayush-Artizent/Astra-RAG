// S4: query latency/errors from the library while `codegraph sync` runs as a child process.
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const cgmod = require('@colbymchenry/codegraph');
const CodeGraph = cgmod.CodeGraph || cgmod.default || cgmod;

const project = path.resolve(__dirname, process.argv[2] || 'fixtures/cg-src');
const nChange = Number(process.argv[3] || 40);
const bin = path.resolve(__dirname, 'node_modules/@colbymchenry/codegraph-win32-x64/bin/codegraph.cmd');

function listSource(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === '.codegraph' || e.name === 'node_modules' || e.name === '.git') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) listSource(p, out);
    else if (/\.(ts|py|js)$/.test(e.name)) out.push(p);
  }
  return out;
}

(async () => {
  const files = listSource(project).slice(0, nChange);
  for (const f of files) fs.appendFileSync(f, `\n// spike-edit ${Date.now()}\nfunction spikeFn${Math.floor(Math.random() * 1e9)}() { return 1; }\n`);
  console.log('edited', files.length, 'files');

  const cg = await CodeGraph.open(project);
  const lat = [];
  const errors = [];
  let stop = false;
  const loop = (async () => {
    while (!stop) {
      const t = process.hrtime.bigint();
      try { cg.searchNodes('findPath', { limit: 5 }); cg.getStats(); } catch (e) { errors.push(String(e.message || e).slice(0, 120)); }
      lat.push(Number(process.hrtime.bigint() - t) / 1e6);
      await new Promise((r) => setTimeout(r, 10));
    }
  })();

  const t0 = Date.now();
  const child = spawn(bin, ['sync', project], { shell: true, env: { ...process.env, CODEGRAPH_TELEMETRY: '0' } });
  let out = '';
  child.stdout.on('data', (d) => (out += d));
  child.stderr.on('data', (d) => (out += d));
  const code = await new Promise((r) => child.on('close', r));
  const syncMs = Date.now() - t0;
  stop = true;
  await loop;

  lat.sort((a, b) => a - b);
  const pct = (p) => lat[Math.min(lat.length - 1, Math.floor(lat.length * p))].toFixed(1);
  console.log({ exit: code, syncMs, queries: lat.length, p50ms: pct(0.5), p95ms: pct(0.95), maxMs: lat[lat.length - 1].toFixed(1), errors: [...new Set(errors)] });
  console.log(out.split(/\r?\n/).filter(Boolean).slice(-6).join('\n'));
  // does a fresh query see the new symbol after sync (same open handle)?
  const hit = cg.searchNodes('spikeFn', { limit: 3 });
  console.log('post-sync sees new symbols on existing handle:', hit.length > 0);
  cg.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
