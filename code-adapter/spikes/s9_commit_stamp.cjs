// Does CodeGraph record the commit an index was built/synced at? Read its metadata table directly.
const path = require('path');
const { execFileSync } = require('child_process');
const { DatabaseSync } = require('node:sqlite');

for (const name of ['django', 'cg-src']) {
  const root = path.resolve(__dirname, 'fixtures', name);
  const db = new DatabaseSync(path.join(root, '.codegraph', 'codegraph.db'), { readOnly: true });
  const rows = db.prepare('SELECT key, value FROM metadata ORDER BY key').all();
  let head = null;
  try { head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); } catch { /* not a git repo */ }
  console.log(`\n===== ${name}   git HEAD of the folder: ${head ? head.slice(0, 12) : '(not a git repo)'}`);
  for (const r of rows) console.log('  ', r.key.padEnd(34), String(r.value).slice(0, 60));
  db.close();
}
