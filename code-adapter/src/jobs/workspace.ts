import fs from 'node:fs';
import path from 'node:path';

/** Directories the adapter and CodeGraph own. They are never scanned and never deleted by a sync. */
const SKIP = new Set(['.git', '.codegraph']);

/**
 * Real symlinks in a working tree, as paths relative to `dir`. The clone is made with `core.symlinks=false`, so
 * there should be none; finding one means that protection failed, and the project must not be indexed.
 * Stops after `limit` hits.
 */
export function findSymlinks(dir: string, limit = 20): string[] {
  const found: string[] = [];
  const stack = [dir];
  while (stack.length > 0 && found.length < limit) {
    const current = stack.pop() as string;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (current === dir && SKIP.has(entry.name)) continue;
      const full = path.join(current, entry.name);
      if (entry.isSymbolicLink()) {
        found.push(path.relative(dir, full).split(path.sep).join('/'));
        if (found.length >= limit) break;
      } else if (entry.isDirectory()) {
        stack.push(full);
      }
    }
  }
  return found;
}

/**
 * Deletes a folder, retrying briefly: on Windows a just-killed process can still hold a file for a moment.
 * Does nothing if the folder is already gone.
 */
export async function removeDir(dir: string): Promise<void> {
  await fs.promises.rm(dir, { recursive: true, force: true, maxRetries: 8, retryDelay: 250 });
}

/** True if the folder exists and has anything in it. */
export function isNonEmptyDir(dir: string): boolean {
  try {
    return fs.readdirSync(dir).length > 0;
  } catch {
    return false;
  }
}
