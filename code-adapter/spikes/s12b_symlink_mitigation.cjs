// Mitigation test: a repo that CONTAINS a symlink entry (mode 120000) pointing at another tenant's file.
// Clone it with core.symlinks=false so git writes a plain text file instead of a link, then index it.
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { CodeGraph } = require('@colbymchenry/codegraph');

const git = (cwd, ...a) => execFileSync('git', a, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const gitIn = (cwd, input, ...a) => execFileSync('git', a, { cwd, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();

(async () => {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-symmit-'));
  const victim = path.join(data, 'orgB', 'p1');
  fs.mkdirSync(victim, { recursive: true });
  fs.writeFileSync(path.join(victim, 'secret.ts'), 'export function victimSecretFn() { return "ORG-B-PRIVATE-VALUE"; }\n');

  // The "customer" repo: one normal file plus a symlink ENTRY, created without needing OS symlink rights.
  const origin = path.join(data, 'origin');
  fs.mkdirSync(path.join(origin, 'src'), { recursive: true });
  git(origin, 'init', '-q', '-b', 'main');
  git(origin, 'config', 'user.email', 't@t'); git(origin, 'config', 'user.name', 't');
  fs.writeFileSync(path.join(origin, 'src', 'ok.ts'), 'export function legit() { return 1; }\n');
  git(origin, 'add', '-A');
  const blob = gitIn(origin, '../../../orgB/p1/secret.ts', 'hash-object', '-w', '--stdin');
  git(origin, 'update-index', '--add', '--cacheinfo', `120000,${blob},src/leak.ts`);
  git(origin, 'commit', '-q', '-m', 'repo with a symlink entry');
  console.log('entry in the repo:', git(origin, 'ls-files', '-s', 'src/leak.ts').split('\t')[0], '(120000 = symlink)');

  const proj = path.join(data, 'orgA', 'p1');
  fs.mkdirSync(path.dirname(proj), { recursive: true });
  git(data, '-c', 'core.symlinks=false', 'clone', '-q', '--no-local', `file://${origin.replace(/\\/g, '/')}`, proj);

  const leak = path.join(proj, 'src', 'leak.ts');
  const st = fs.lstatSync(leak);
  console.log('after clone with core.symlinks=false: is a real symlink =', st.isSymbolicLink(), '| plain file content =', JSON.stringify(fs.readFileSync(leak, 'utf8')));

  (await CodeGraph.init(proj, { index: true })).close();
  const cg = await CodeGraph.open(proj, { readOnly: true });
  const foreign = cg.searchNodes('victimSecretFn', { limit: 5 }).some((r) => r.node.name === 'victimSecretFn');
  const own = cg.searchNodes('legit', { limit: 5 }).some((r) => r.node.name === 'legit');
  console.log('own symbol indexed =', own, '| other tenant\'s symbol indexed =', foreign);
  cg.close();
  fs.rmSync(data, { recursive: true, force: true });
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
