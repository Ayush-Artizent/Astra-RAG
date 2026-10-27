// How does searchNodes behave for keyword-style queries? (camelCase names, multiple words)
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { CodeGraph } = require('@colbymchenry/codegraph');

const show = (cg, q, opts = { limit: 8 }) => {
  const r = cg.searchNodes(q, opts);
  console.log(`\nsearchNodes(${JSON.stringify(q)}) -> ${r.length}`);
  for (const x of r.slice(0, 6)) console.log('  ', x.score.toFixed(1).padStart(6), x.node.kind.padEnd(9), x.node.qualifiedName, x.node.filePath);
};

(async () => {
  // 1. tiny repo
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-kw-'));
  fs.mkdirSync(path.join(dir, 'lib'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'lib', 'token.ts'),
    'export function issueToken(user: string) { return user; }\nexport function expireToken(t: string) { return t; }\nexport function validate_token(t: string) { return t; }\n');
  (await CodeGraph.init(dir, { index: true })).close();
  const small = await CodeGraph.open(dir, { readOnly: true });
  console.log('===== tiny repo (issueToken, expireToken, validate_token in lib/token.ts)');
  for (const q of ['token', 'Token', 'issue', 'issueToken', 'expire token', 'token expire']) show(small, q);
  small.close();

  // 2. django, same kind of queries
  const dj = await CodeGraph.open(path.resolve(__dirname, 'fixtures/django'), { readOnly: true });
  console.log('\n===== django');
  for (const q of ['token', 'csrf token', 'session expiry', 'password reset', 'authenticate user', 'login']) show(dj, q, { limit: 6 });
  dj.close();
  fs.rmSync(dir, { recursive: true, force: true });
})();
