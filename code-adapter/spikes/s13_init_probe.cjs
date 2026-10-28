// What does `codegraph init <dir>` do when run non-interactively from the adapter? Output, prompts, side effects.
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync, execFileSync } = require('child_process');

const git = (cwd, ...a) => execFileSync('git', a, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const ls = (dir) => fs.readdirSync(dir).sort().join(', ');

console.log('git', git(process.cwd(), '--version'));
const gitMajorMinor = /(\d+)\.(\d+)/.exec(git(process.cwd(), '--version'));
console.log('GIT_CONFIG_COUNT env config needs git >= 2.31:', Number(gitMajorMinor[1]) > 2 || (Number(gitMajorMinor[1]) === 2 && Number(gitMajorMinor[2]) >= 31));

const shim = path.join(path.dirname(require.resolve('@colbymchenry/codegraph/package.json')), 'npm-shim.js');
console.log('launcher script exists:', fs.existsSync(shim), '\n');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-init-'));
git(dir, 'init', '-q', '-b', 'main');
git(dir, 'config', 'user.email', 't@t'); git(dir, 'config', 'user.name', 't');
fs.mkdirSync(path.join(dir, 'src'));
fs.writeFileSync(path.join(dir, 'src', 'a.ts'), 'export function alpha() { return beta(); }\nexport function beta() { return 1; }\n');
git(dir, 'add', '-A'); git(dir, 'commit', '-q', '-m', 'A');
const head = git(dir, 'rev-parse', 'HEAD');

const hooksBefore = ls(path.join(dir, '.git', 'hooks'));
console.log('before:  files =', ls(dir), '| hooks =', hooksBefore);

const t = Date.now();
const r = spawnSync(process.execPath, [shim, 'init', dir], { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8', env: { ...process.env, CODEGRAPH_TELEMETRY: '0' }, timeout: 120000 });
console.log(`\nexit code ${r.status}  in ${Date.now() - t} ms   (stdin was closed, so any prompt would have failed or defaulted)`);
console.log('--- stdout');
console.log(r.stdout);
console.log('--- stderr');
console.log(r.stderr || '(empty)');

console.log('after:   files =', ls(dir), '| hooks =', ls(path.join(dir, '.git', 'hooks')));
console.log('git status --porcelain:', JSON.stringify(git(dir, 'status', '--porcelain')));
console.log('hooks changed:', hooksBefore !== ls(path.join(dir, '.git', 'hooks')));
console.log('.git/info/exclude:', JSON.stringify(fs.readFileSync(path.join(dir, '.git', 'info', 'exclude'), 'utf8').split('\n').filter((l) => l && !l.startsWith('#'))));
console.log('.gitignore exists:', fs.existsSync(path.join(dir, '.gitignore')));

const { DatabaseSync } = require('node:sqlite');
const db = new DatabaseSync(path.join(dir, '.codegraph', 'codegraph.db'), { readOnly: true });
const stamp = db.prepare("SELECT value FROM project_metadata WHERE key = 'indexed_at_commit'").get();
db.close();
console.log('\nstamp after CLI init:', stamp && stamp.value, '| HEAD:', head, '| equal:', stamp && stamp.value === head);
fs.rmSync(dir, { recursive: true, force: true });
