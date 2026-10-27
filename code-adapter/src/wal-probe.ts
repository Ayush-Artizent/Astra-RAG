import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import type { DatabaseSync as DatabaseSyncType } from 'node:sqlite';

// Loaded through require so bundlers used by the test runner do not try to resolve `node:sqlite`.
const { DatabaseSync } = createRequire(import.meta.url)('node:sqlite') as {
  DatabaseSync: typeof DatabaseSyncType;
};

/**
 * Opens a file-backed scratch database and checks that SQLite switches it to WAL (A4).
 * It must be file-backed: an in-memory database reports `memory` and would fail wrongly.
 */
export function walProbe(): 'ok' | 'failed' {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'astra-wal-'));
  try {
    const db = new DatabaseSync(path.join(dir, 'probe.db'));
    try {
      const row = db.prepare('PRAGMA journal_mode = wal').get() as { journal_mode?: string } | undefined;
      return row?.journal_mode === 'wal' ? 'ok' : 'failed';
    } finally {
      db.close();
    }
  } catch {
    return 'failed';
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}
