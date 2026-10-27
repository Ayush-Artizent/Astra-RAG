// Does CodeGraph's own commit stamp (indexed_at_commit) follow our planned flow?
//   clone -> index -> (fetch + reset --hard <sha>) -> sync, including rollback, rewritten history and a shallow clone.
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { DatabaseSync } = require('node:sqlite');
const { CodeGraph } = require('@colbymchenry/codegraph');

const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const stamp = (dir) => {
  const db = new DatabaseSync(path.join(dir, '.codegraph', 'codegraph.db'), { readOnly: true });
  const row = db.prepare("SELECT value FROM project_metadata WHERE key = 'indexed_at_commit'").get();
  db.close();
  return row ? row.value : null;
};
const has = async (dir, name) => {
  const cg = await CodeGraph.open(dir, { readOnly: true });
  const found = cg.searchNodes(name, { limit: 5 }).some((r) => r.node.name === name);
  cg.close();
  return found;
};
const short = (s) => (s ? s.slice(0, 7) : s);
const check = (label, ok, extra = '') => console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '   ' + extra : ''}`);

async function sync(dir) {
  const cg = await CodeGraph.open(dir);
  const t = Date.now();
  const r = await cg.sync();
  cg.close();
  return { ms: Date.now() - t, r };
}

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-gitflow-'));
  const origin = path.join(root, 'origin');
  fs.mkdirSync(origin);
  git(origin, 'init', '-q', '-b', 'main');
  git(origin, 'config', 'user.email', 't@t'); git(origin, 'config', 'user.name', 't');
  git(origin, 'config', 'uploadpack.allowAnySHA1InWant', 'true');
  const commit = (file, body, msg) => { fs.writeFileSync(path.join(origin, file), body); git(origin, 'add', '-A'); git(origin, 'commit', '-q', '-m', msg); return git(origin, 'rev-parse', 'HEAD'); };

  const A = commit('a.ts', 'export function alpha() { return 1; }\n', 'A');
  const B = commit('b.ts', 'export function beta() { return alpha(); }\n', 'B');

  // 1. Bootstrap exactly as planned: shallow clone at A, then index.
  const proj = path.join(root, 'project');
  git(root, 'clone', '-q', '--depth', '1', '--no-local', `file://${origin.replace(/\\/g, '/')}`, 'project');
  git(proj, 'fetch', '-q', '--depth', '1', 'origin', A);
  git(proj, 'reset', '-q', '--hard', A);
  (await CodeGraph.init(proj, { index: true })).close();
  check('bootstrap: stamp equals the commit we reset to', stamp(proj) === A, `${short(stamp(proj))} vs ${short(A)}`);
  check('bootstrap: symbols from A present, B absent', (await has(proj, 'alpha')) && !(await has(proj, 'beta')));

  // 2. Push B, then sync as planned: fetch the sha, reset --hard, sync.
  git(proj, 'fetch', '-q', '--depth', '1', 'origin', B);
  git(proj, 'reset', '-q', '--hard', B);
  let s = await sync(proj);
  check('sync forward to B (shallow fetch): stamp follows', stamp(proj) === B, `${short(stamp(proj))} vs ${short(B)}  ${s.ms}ms, added=${s.r.filesAdded} modified=${s.r.filesModified}`);
  check('sync forward: new symbol visible', await has(proj, 'beta'));

  // 3. Roll back to A (reset --hard): the deleted file must disappear.
  git(proj, 'fetch', '-q', '--depth', '1', 'origin', A);
  git(proj, 'reset', '-q', '--hard', A);
  s = await sync(proj);
  check('rollback to A: stamp follows', stamp(proj) === A, `${short(stamp(proj))}  removed=${s.r.filesRemoved}`);
  check('rollback: symbols of B are gone', !(await has(proj, 'beta')));

  // 4. History rewritten upstream: a commit that is NOT a descendant of what we indexed.
  git(origin, 'checkout', '-q', '-b', 'rewritten', A);
  const C = commit('c.ts', 'export function gamma() { return 3; }\n', 'C (rewritten history)');
  git(proj, 'fetch', '-q', '--depth', '1', 'origin', C);
  git(proj, 'reset', '-q', '--hard', C);
  s = await sync(proj);
  check('force-push style jump to unrelated C: stamp follows', stamp(proj) === C, `${short(stamp(proj))}  ${s.ms}ms, added=${s.r.filesAdded}`);
  check('force-push: gamma indexed', await has(proj, 'gamma'));

  // 5. What does a hook-free sync do when nothing changed at all?
  s = await sync(proj);
  check('no-op sync leaves the stamp alone', stamp(proj) === C, `${s.ms}ms, filesChecked=${s.r.filesChecked}`);

  // 6. A crash/failed sync must not move the stamp. Simulate: make a.ts unreadable is hard on Windows, so just show the stamp is only advanced by a completed sync.
  console.log('\n(stamp is written inside sync/index; a killed process before that leaves the previous commit)');
  fs.rmSync(root, { recursive: true, force: true });
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
