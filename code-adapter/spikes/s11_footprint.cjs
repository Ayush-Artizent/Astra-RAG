// How much of the on-disk copy is source CodeGraph actually uses?
const fs = require('fs');
const path = require('path');
const { DatabaseSync } = require('node:sqlite');

function walk(dir, skip, cb) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (skip.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, skip, cb);
    else if (e.isFile()) cb(p, fs.statSync(p).size);
  }
}
const mb = (n) => (n / 1048576).toFixed(1).padStart(7) + ' MB';

const proj = path.resolve(__dirname, 'fixtures', 'django');
const db = new DatabaseSync(path.join(proj, '.codegraph', 'codegraph.db'), { readOnly: true });
const indexed = db.prepare('SELECT COUNT(*) n, COALESCE(SUM(size),0) bytes FROM files').get();
const byLang = db.prepare('SELECT language, COUNT(*) n, SUM(size) bytes FROM files GROUP BY language ORDER BY bytes DESC LIMIT 6').all();

let total = 0, count = 0;
const byExt = new Map();
walk(proj, new Set(['.git', '.codegraph']), (p, size) => {
  total += size; count++;
  const ext = path.extname(p).toLowerCase() || '(none)';
  byExt.set(ext, (byExt.get(ext) || 0) + size);
});

console.log('files on disk (excluding .git and .codegraph):', count, mb(total));
console.log('files CodeGraph indexed:                      ', indexed.n, mb(indexed.bytes));
console.log('=> source CodeGraph reads:', ((indexed.bytes / total) * 100).toFixed(0) + '% of the working tree');
console.log('\nlargest non-indexed extensions:');
const indexedExts = new Set(db.prepare('SELECT path FROM files').all().map((r) => path.extname(r.path).toLowerCase() || '(none)'));
[...byExt.entries()].filter(([e]) => !indexedExts.has(e)).sort((a, b) => b[1] - a[1]).slice(0, 6).forEach(([e, b]) => console.log('  ', e.padEnd(10), mb(b)));
console.log('\nindexed languages:'); byLang.forEach((r) => console.log('  ', String(r.language).padEnd(12), String(r.n).padStart(5), 'files', mb(r.bytes)));
db.close();
