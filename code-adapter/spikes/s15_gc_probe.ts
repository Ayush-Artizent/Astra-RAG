// Why did reconcile not run gc after two syncs? What does `git count-objects -v` say in that situation?
import '../src/env.js';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { git, gitEnvironment, looseObjects } from '../src/jobs/git.js';
import { makeOrigin } from '../test/git-helpers.js';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-gcprobe-'));
const emptyConfig = path.join(root, 'empty.gitconfig');
fs.writeFileSync(emptyConfig, '');
const env = gitEnvironment({ allowFileRepos: true, credential: null, repoUrl: null, emptyConfigFile: emptyConfig });
const run = (cwd?: string) => ({ env, timeoutMs: 60_000, cwd });

const origin = makeOrigin(root, 'origin', { 'a.ts': 'export function a() { return 1; }\n' });
const clone = path.join(root, 'clone');
await git(['-c', 'core.symlinks=false', 'clone', '--depth', '1', '--no-tags', '--', origin.url, clone], run());

const show = async (label: string) => {
  const raw = await git(['count-objects', '-v'], run(clone));
  console.log(`\n--- ${label}\n${raw}\n=> parsed`, await looseObjects(clone, run()));
};
await show('after clone');

for (let i = 0; i < 2; i++) {
  const sha = origin.commit({ [`web/big${i}.ts`]: `export const data${i} = "${'x'.repeat(8000)}";\n` });
  await git(['fetch', '--depth', '1', '--no-tags', '--no-recurse-submodules', 'origin', sha], run(clone));
  await git(['reset', '--hard', '--quiet', sha], run(clone));
  await show(`after sync ${i + 1}`);
}
fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
