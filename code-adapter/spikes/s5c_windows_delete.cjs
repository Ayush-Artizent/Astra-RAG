// Can the index dir be deleted while a read-only handle is open (Windows)?
process.env.CODEGRAPH_TELEMETRY = '0';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { CodeGraph } = require('@colbymchenry/codegraph');

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-del-'));
  fs.writeFileSync(path.join(dir, 'a.ts'), 'export function one() { return 1; }\n');
  const w = await CodeGraph.init(dir, { index: true });
  w.close();
  const cg = await CodeGraph.open(dir, { readOnly: true });
  try {
    fs.rmSync(path.join(dir, '.codegraph'), { recursive: true, force: false });
    console.log('delete while open: SUCCEEDED');
  } catch (e) {
    console.log('delete while open: FAILED with', e.code);
  }
  cg.close();
  try {
    fs.rmSync(dir, { recursive: true, force: true });
    console.log('delete after close: ok');
  } catch (e) {
    console.log('delete after close: FAILED with', e.code);
  }
})();
