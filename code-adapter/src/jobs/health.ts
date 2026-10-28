import fs from 'node:fs';
import path from 'node:path';
import { databasePath, isInitialized, openReadOnly } from '../codegraph.js';
import { readIndexedCommit } from './stamp.js';

export type Health = { ok: true; stamp: string } | { ok: false; reason: string };

/**
 * Whether a project's folder is whole enough to keep syncing: git data present, an index that opens and reads,
 * is not marked failed or interrupted, and carries a commit stamp. Anything else means the project is rebuilt.
 *
 * The caller must be the only job running on the project, so an index marked `indexing` is a truncated one, not
 * one being built right now.
 *
 * Limit: this opens the index and reads its tables. It does not run SQLite's full integrity check, which takes
 * seconds on a large index, so damage in pages that are never read is not detected.
 */
export async function checkProject(dir: string): Promise<Health> {
  if (!fs.existsSync(dir)) return { ok: false, reason: 'the project folder is missing' };
  if (!fs.existsSync(path.join(dir, '.git'))) return { ok: false, reason: 'the git data is missing' };
  if (!isInitialized(dir)) {
    // CodeGraph also answers "not initialised" for a file that is not a database at all.
    let present = false;
    try {
      present = fs.existsSync(databasePath(dir));
    } catch {
      // no database path means no index
    }
    return { ok: false, reason: present ? 'the index file is damaged' : 'the index is missing' };
  }

  let cg;
  try {
    cg = await openReadOnly(dir);
  } catch (e) {
    return { ok: false, reason: `the index cannot be opened: ${e instanceof Error ? e.message : String(e)}` };
  }
  try {
    const state = cg.getIndexState();
    if (state === 'failed' || state === 'indexing') return { ok: false, reason: `the index is marked ${state}` };
    cg.getStats();
  } catch (e) {
    return { ok: false, reason: `the index cannot be read: ${e instanceof Error ? e.message : String(e)}` };
  } finally {
    try {
      cg.close();
    } catch {
      // nothing to release
    }
  }

  const stamp = readIndexedCommit(dir);
  if (!stamp) return { ok: false, reason: 'the index has no commit stamp' };
  return { ok: true, stamp };
}
