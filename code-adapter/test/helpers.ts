import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import '../src/env.js';
import type { Config } from '../src/config.js';
import { signEnvelope } from '../src/envelope.js';

// Shared setup for the tests that run the real HTTP routes against real CodeGraph indexes.

const lib = createRequire(import.meta.url)('@colbymchenry/codegraph') as {
  CodeGraph: { init(root: string, o: { index: boolean }): Promise<{ close(): void }> };
};

export const TEST_KEY = 'test-key-0123456789abcdef';

export function testConfig(dataDir: string): Config {
  return {
    port: 0,
    host: '127.0.0.1',
    dataDir,
    envelopeKey: TEST_KEY,
    maxEnvelopeLifetimeSeconds: 300,
    clockSkewSeconds: 30,
  };
}

/** Writes the files under `<dataDir>/<org>/<project>/` and builds a real CodeGraph index there. */
export async function seedProject(
  dataDir: string,
  org: string,
  project: string,
  files: Record<string, string>,
): Promise<void> {
  const dir = path.join(dataDir, org, project);
  for (const [rel, text] of Object.entries(files)) {
    const file = path.join(dir, rel);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
  }
  (await lib.CodeGraph.init(dir, { index: true })).close();
}

const now = () => Math.floor(Date.now() / 1000);

/** A valid signed envelope header value, good for one minute. */
export function signedEnvelope(org: string, project: string, scopes: string[] = ['query']): string {
  return signEnvelope(
    { org_id: org, project_id: project, scopes, request_id: 'env-req', iat: now(), exp: now() + 60 },
    TEST_KEY,
  );
}

/** orgA/p1: a call chain render <- handle <- route <- main <- start, two `draw` methods, token helpers. */
export const ORG_A_FILES: Record<string, string> = {
  'web/app.ts': [
    'export function render(page: string) { return page; }',
    'export function handle(req: string) { return render(req); }',
    'export function route(req: string) { return handle(req); }',
    'export function main() { return route("x"); }',
    'export class Widget { draw() { return render("w"); } }',
    'export class Panel { draw() { return 1; } }',
    '',
  ].join('\n'),
  'web/index.ts': "import { main } from './app';\nexport function start() { return main(); }\n",
  'lib/token.ts':
    'export function issueToken(user: string) { return user; }\nexport function expireToken(t: string) { return t; }\n',
};

/** orgB/p1: a different org that reuses the project id `p1`. */
export const ORG_B_FILES: Record<string, string> = {
  'billing/invoice.ts': 'export function total(n: number) { return n * 2; }\n',
};

/** The commit the tests pretend orgA/p1 was synced to. */
export const ORG_A_SHA = 'a1b2c3d';
export const commitShaFor = (org: string, project: string) => (org === 'orgA' && project === 'p1' ? ORG_A_SHA : null);
