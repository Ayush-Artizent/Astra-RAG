// Why is the source text null after a real bootstrap, and which phases does the real CLI report?
import '../src/env.js';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { openReadOnly } from '../src/codegraph.js';
import { createBootstrapExecutor } from '../src/jobs/bootstrap.js';
import { ensureEmptyGitConfig } from '../src/jobs/common.js';
import { ProjectRegistry } from '../src/projects.js';
import { validatePathWithinRoot } from '../node_modules/@colbymchenry/codegraph-win32-x64/lib/dist/utils.js';
import { makeOrigin } from '../test/git-helpers.js';
import { ORG_A_FILES, testConfig } from '../test/helpers.js';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-dbg-'));
const dataDir = path.join(root, 'data');
fs.mkdirSync(dataDir);
const origin = makeOrigin(root, 'origin', ORG_A_FILES);
const config = { ...testConfig(dataDir), allowFileRepos: true, bootstrapTimeoutMs: 180_000, syncTimeoutMs: 180_000 };
const registry = new ProjectRegistry({ dataDir });
const exec = createBootstrapExecutor({ config, registry, emptyGitConfig: ensureEmptyGitConfig(dataDir) });

const phases: string[] = [];
const result = await exec({
  job: { id: 'j', orgId: 'orgA', projectId: 'p1', type: 'bootstrap' } as never,
  project: { orgId: 'orgA', projectId: 'p1', repoUrl: origin.url, branch: null, credentialsRef: null, createdAt: 0, bootstrappedAt: null },
  update: (p) => phases.push(`${p.phase}:${p.progress}`),
  signal: new AbortController().signal,
});
console.log('result', result);
console.log('phases reported:', phases);

const dir = path.join(dataDir, 'orgA', 'p1');
const cg = await openReadOnly(dir);
const hit = cg.searchNodes('handle', { limit: 3 }).find((r) => r.node.name === 'handle')!.node;
console.log('node.filePath =', JSON.stringify(hit.filePath), ' root =', dir);
console.log('file exists at join:', fs.existsSync(path.join(dir, hit.filePath)));
console.log('getCode =>', JSON.stringify((await cg.getCode(hit.id))?.slice(0, 60) ?? null));
try {
  console.log('validatePathWithinRoot =>', validatePathWithinRoot(dir, hit.filePath));
} catch (e) {
  console.log('validatePathWithinRoot threw', (e as Error).message);
}
console.log('realpath of root     :', fs.realpathSync(dir));
console.log('realpath.native root :', fs.realpathSync.native(dir));
cg.close();
registry.closeAll();
fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
