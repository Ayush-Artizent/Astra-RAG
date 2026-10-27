// What happens if the working tree is deleted after indexing? And how big is each part on disk?
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { CodeGraph } = require('@colbymchenry/codegraph');

const git = (cwd, ...a) => execFileSync('git', a, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
function size(p) {
  let total = 0;
  const stack = [p];
  while (stack.length) {
    const cur = stack.pop();
    let st;
    try { st = fs.lstatSync(cur); } catch { continue; }
    if (st.isDirectory()) { for (const e of fs.readdirSync(cur)) stack.push(path.join(cur, e)); } else total += st.size;
  }
  return total;
}
const mb = (n) => (n / 1048576).toFixed(1).padStart(7) + ' MB';

(async () => {
  console.log('===== disk use of a real project (Django, shallow clone, depth 1)');
  const dj = path.resolve(__dirname, 'fixtures', 'django');
  if (fs.existsSync(dj)) {
    const top = fs.readdirSync(dj).filter((n) => n !== '.git' && n !== '.codegraph');
    const tree = top.reduce((a, n) => a + size(path.join(dj, n)), 0);
    console.log('  source working tree ', mb(tree));
    console.log('  .git                ', mb(size(path.join(dj, '.git'))));
    console.log('  .codegraph (index)  ', mb(size(path.join(dj, '.codegraph'))));
  }

  console.log('\n===== delete the working tree after indexing (tiny repo)');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-clean-'));
  git(root, 'init', '-q', '-b', 'main');
  git(root, 'config', 'user.email', 't@t'); git(root, 'config', 'user.name', 't');
  fs.mkdirSync(path.join(root, 'src'));
  fs.writeFileSync(path.join(root, 'src', 'a.ts'), 'export function alpha() { return beta(); }\nexport function beta() { return 1; }\n');
  git(root, 'add', '-A'); git(root, 'commit', '-q', '-m', 'A');
  (await CodeGraph.init(root, { index: true })).close();

  let cg = await CodeGraph.open(root, { readOnly: true });
  const alpha = cg.searchNodes('alpha', { limit: 3 }).find((r) => r.node.name === 'alpha').node;
  console.log('  before delete: getCode(alpha) =', JSON.stringify((await cg.getCode(alpha.id) || '').slice(0, 40)));
  cg.close();

  // Delete the source files but keep .git and .codegraph.
  fs.rmSync(path.join(root, 'src'), { recursive: true, force: true });

  cg = await CodeGraph.open(root, { readOnly: true });
  const still = cg.searchNodes('alpha', { limit: 3 }).some((r) => r.node.name === 'alpha');
  let code;
  try { code = await cg.getCode(alpha.id); } catch (e) { code = `THROWS ${e.message}`; }
  console.log('  after delete:  index still answers searchNodes(alpha) =', still, '|  getCode(alpha) =', JSON.stringify(code));
  cg.close();

  // What would a sync do now? (Run on a copy so the check is safe.)
  cg = await CodeGraph.open(root);
  const r = await cg.sync();
  cg.close();
  cg = await CodeGraph.open(root, { readOnly: true });
  const afterSync = cg.searchNodes('alpha', { limit: 3 }).some((x) => x.node.name === 'alpha');
  console.log(`  sync with no source on disk: filesRemoved=${r.filesRemoved}  symbol alpha still indexed = ${afterSync}`);
  cg.close();

  // Restore: git can bring the tree back from .git, then a sync repairs the index.
  git(root, 'checkout', '-q', '--', '.');
  cg = await CodeGraph.open(root);
  const r2 = await cg.sync();
  cg.close();
  cg = await CodeGraph.open(root, { readOnly: true });
  console.log(`  after git checkout + sync: filesAdded=${r2.filesAdded}  alpha indexed = ${cg.searchNodes('alpha', { limit: 3 }).some((x) => x.node.name === 'alpha')}`);
  cg.close();
  fs.rmSync(root, { recursive: true, force: true });
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
