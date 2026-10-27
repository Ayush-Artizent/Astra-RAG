import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import '../src/env.js';
import { ProjectRegistry } from '../src/projects.js';

// Real CodeGraph, real SQLite. Builds two tiny indexed projects that share a project id in two orgs.
const lib = createRequire(import.meta.url)('@colbymchenry/codegraph') as {
  CodeGraph: { init(root: string, o: { index: boolean }): Promise<{ close(): void }> };
};

let dataDir: string;
let registry: ProjectRegistry;

async function seed(org: string, project: string, files: Record<string, string>) {
  const dir = path.join(dataDir, org, project);
  for (const [rel, text] of Object.entries(files)) {
    const file = path.join(dir, rel);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
  }
  const cg = await lib.CodeGraph.init(dir, { index: true });
  cg.close();
}

beforeAll(async () => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-projects-'));
  await seed('orgA', 'p1', {
    'src/tokens.ts': 'export class TokenService { issue(user: string) { return user + "-a"; } }\n',
  });
  await seed('orgB', 'p1', {
    'src/billing.ts': 'export class InvoiceService { total(n: number) { return n * 2; } }\n',
  });
  registry = new ProjectRegistry({ dataDir, idleMs: 0 });
}, 120_000);

afterAll(() => {
  registry.closeAll();
  fs.rmSync(dataDir, { recursive: true, force: true });
});

describe('ProjectRegistry with real indexes', () => {
  it('serves an indexed project read-only', async () => {
    const lease = await registry.acquire('orgA', 'p1');
    try {
      expect(lease.project.ready).toBe(true);
      if (!lease.project.ready) return;
      expect(lease.project.indexState).toBe('complete');
      expect(lease.project.cg.getJournalMode()).toBe('wal');
      const hit = lease.project.cg.searchNodes('TokenService', { limit: 3 });
      expect(hit.some((r) => r.node.name === 'TokenService')).toBe(true);
    } finally {
      lease.release();
    }
  });

  it('does not let one org see another org symbols, even with the same project id', async () => {
    const a = await registry.acquire('orgA', 'p1');
    const b = await registry.acquire('orgB', 'p1');
    try {
      if (!a.project.ready || !b.project.ready) throw new Error('expected both ready');
      expect(a.project.cg.searchNodes('InvoiceService', { limit: 5 })).toHaveLength(0);
      expect(b.project.cg.searchNodes('TokenService', { limit: 5 })).toHaveLength(0);
      expect(b.project.cg.searchNodes('InvoiceService', { limit: 5 }).length).toBeGreaterThan(0);
    } finally {
      a.release();
      b.release();
    }
  });

  it('reports not_indexed for a project with no index', async () => {
    const lease = await registry.acquire('orgA', 'p2');
    expect(lease.project).toMatchObject({ ready: false, reason: 'not_indexed' });
  });

  it('reports not_indexed for a directory that exists but is not indexed', async () => {
    fs.mkdirSync(path.join(dataDir, 'orgA', 'empty'), { recursive: true });
    const lease = await registry.acquire('orgA', 'empty');
    expect(lease.project).toMatchObject({ ready: false, reason: 'not_indexed' });
  });

  it('can delete a project index after evicting its handle (rebuild case on Windows)', async () => {
    await seed('orgA', 'rebuild', { 'a.ts': 'export function one() { return 1; }\n' });
    (await registry.acquire('orgA', 'rebuild')).release();
    registry.evict('orgA', 'rebuild');
    fs.rmSync(path.join(dataDir, 'orgA', 'rebuild', '.codegraph'), { recursive: true, force: true });
    const lease = await registry.acquire('orgA', 'rebuild');
    expect(lease.project).toMatchObject({ ready: false, reason: 'not_indexed' });
  });
});
