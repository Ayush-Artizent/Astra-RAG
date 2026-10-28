import fs from 'node:fs';
import { databasePath } from '../codegraph.js';
import { DatabaseSync } from '../sqlite.js';

/** The key CodeGraph 1.6.2 uses. A test fails if an upgrade removes or renames it (work plan, decision 6). */
export const INDEXED_COMMIT_KEY = 'indexed_at_commit';

/**
 * The commit a project's index reflects, as recorded by CodeGraph itself after a full index or a successful
 * sync. It is written together with the index data, so it cannot name a commit the index does not contain.
 * Returns null when there is no index, no stamp, or the database cannot be read.
 *
 * This reads an internal table of CodeGraph's database, because the library has no accessor for it.
 */
export function readIndexedCommit(projectRoot: string): string | null {
  let file: string;
  try {
    file = databasePath(projectRoot);
    if (!fs.existsSync(file)) return null;
  } catch {
    return null;
  }
  let db: InstanceType<typeof DatabaseSync> | undefined;
  try {
    // `readOnly` works at runtime on Node 22.12+ but is missing from the installed type definitions.
    db = new DatabaseSync(file, { readOnly: true } as unknown as ConstructorParameters<typeof DatabaseSync>[1]);
    db.exec('PRAGMA busy_timeout = 2000');
    const row = db.prepare('SELECT value FROM project_metadata WHERE key = ?').get(INDEXED_COMMIT_KEY) as
      | { value: string }
      | undefined;
    return row?.value || null;
  } catch {
    return null;
  } finally {
    try {
      db?.close();
    } catch {
      // nothing to release
    }
  }
}
