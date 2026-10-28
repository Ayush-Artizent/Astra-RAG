import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Builds real git repositories in a temp folder, to play the part of a customer's git host.

const git = (cwd: string, ...args: string[]): string =>
  execFileSync('git', ['-c', 'core.autocrlf=false', '-c', 'user.email=t@t', '-c', 'user.name=t', ...args], {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();

export interface Origin {
  dir: string;
  /** The `file://` URL the adapter is asked to clone. */
  url: string;
  head(): string;
  /** Writes files (a null value deletes one) and commits them. Returns the new commit. */
  commit(files: Record<string, string | null>, message?: string): string;
  /** Adds a symlink entry (mode 120000) without needing symlink rights on the machine. */
  commitSymlink(linkPath: string, target: string): string;
  branch(name: string, from?: string): void;
  checkout(name: string): void;
}

export function makeOrigin(parent: string, name: string, files: Record<string, string>): Origin {
  const dir = path.join(parent, name);
  fs.mkdirSync(dir, { recursive: true });
  git(dir, 'init', '-q', '-b', 'main');
  // GitHub and GitLab let a client fetch any reachable commit by id; do the same here.
  git(dir, 'config', 'uploadpack.allowAnySHA1InWant', 'true');

  const origin: Origin = {
    dir,
    url: pathToFileURL(dir).href,
    head: () => git(dir, 'rev-parse', 'HEAD'),
    commit(changes, message = 'change') {
      for (const [rel, text] of Object.entries(changes)) {
        const file = path.join(dir, rel);
        if (text === null) {
          fs.rmSync(file, { force: true });
        } else {
          fs.mkdirSync(path.dirname(file), { recursive: true });
          fs.writeFileSync(file, text);
        }
      }
      git(dir, 'add', '-A');
      git(dir, 'commit', '-q', '--allow-empty', '-m', message);
      return origin.head();
    },
    commitSymlink(linkPath, target) {
      const blob = execFileSync('git', ['hash-object', '-w', '--stdin'], { cwd: dir, input: target, encoding: 'utf8' }).trim();
      git(dir, 'update-index', '--add', '--cacheinfo', `120000,${blob},${linkPath}`);
      git(dir, 'commit', '-q', '-m', 'add a symlink entry');
      return origin.head();
    },
    branch: (branchName, from) => void git(dir, 'checkout', '-q', '-b', branchName, ...(from ? [from] : [])),
    checkout: (branchName) => void git(dir, 'checkout', '-q', branchName),
  };
  origin.commit(files, 'initial');
  return origin;
}

/** Runs git in any folder, for assertions. */
export const gitIn = git;
