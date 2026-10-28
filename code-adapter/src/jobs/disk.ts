import fs from 'node:fs';
import path from 'node:path';

export interface DiskUse {
  /** The source files of the working tree. */
  tree: number;
  /** The `.git` folder. */
  git: number;
  /** The `.codegraph` folder: the index database and its write-ahead log. */
  index: number;
}

/** Bytes of every file under `dir`. Links are counted as themselves, never followed. */
async function sizeOf(dir: string): Promise<number> {
  let total = 0;
  const pending = [dir];
  while (pending.length > 0) {
    const current = pending.pop() as string;
    let entries: fs.Dirent[];
    try {
      entries = await fs.promises.readdir(current, { withFileTypes: true });
    } catch {
      continue;
    }
    const files: Promise<number>[] = [];
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(full);
      else files.push(fs.promises.lstat(full).then((s) => s.size, () => 0));
    }
    for (const size of await Promise.all(files)) total += size;
  }
  return total;
}

/**
 * How much disk a project uses, split the way the plan budgets it. Reads asynchronously, so a large project does
 * not stall queries while it is measured.
 */
export async function measureDisk(projectDir: string): Promise<DiskUse> {
  let entries: fs.Dirent[];
  try {
    entries = await fs.promises.readdir(projectDir, { withFileTypes: true });
  } catch {
    return { tree: 0, git: 0, index: 0 };
  }
  const use: DiskUse = { tree: 0, git: 0, index: 0 };
  for (const entry of entries) {
    const full = path.join(projectDir, entry.name);
    const bytes = entry.isDirectory() ? await sizeOf(full) : await fs.promises.lstat(full).then((s) => s.size, () => 0);
    if (entry.name === '.git') use.git += bytes;
    else if (entry.name === '.codegraph') use.index += bytes;
    else use.tree += bytes;
  }
  return use;
}
