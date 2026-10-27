import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { ProblemError } from '../src/errors.js';
import { projectDir, safeRelativePrefix } from '../src/paths.js';

const DATA = path.resolve('some', 'data');

function refused(fn: () => unknown): boolean {
  try {
    fn();
  } catch (e) {
    return e instanceof ProblemError && e.errorCode === 'path_refused';
  }
  return false;
}

describe('projectDir', () => {
  it('builds <data>/<org>/<project>', () => {
    expect(projectDir(DATA, 'orgA', 'p1')).toBe(path.join(DATA, 'orgA', 'p1'));
  });

  it('gives different directories for the same project id in different orgs', () => {
    expect(projectDir(DATA, 'orgA', 'p1')).not.toBe(projectDir(DATA, 'orgB', 'p1'));
  });

  it('refuses traversal and separators in either id', () => {
    const bad = ['..', '../x', 'a/b', 'a\\b', '/abs', 'C:\\x', '.', '', 'a\0b', '..\\..\\x', '%2e%2e'];
    for (const b of bad) {
      expect(refused(() => projectDir(DATA, b, 'p1')), `org ${JSON.stringify(b)}`).toBe(true);
      expect(refused(() => projectDir(DATA, 'orgA', b)), `project ${JSON.stringify(b)}`).toBe(true);
    }
  });
});

describe('safeRelativePrefix', () => {
  it('normalises relative prefixes', () => {
    expect(safeRelativePrefix('src/auth/')).toBe('src/auth');
    expect(safeRelativePrefix('.\\src\\auth')).toBe('src/auth');
    expect(safeRelativePrefix('')).toBe('');
  });

  it('refuses absolute paths, drive letters, parent segments and NUL', () => {
    for (const bad of ['/etc', 'C:\\x', 'C:/x', '../x', 'a/../../x', 'a\\..\\x', 'a\0b']) {
      expect(refused(() => safeRelativePrefix(bad)), JSON.stringify(bad)).toBe(true);
    }
  });
});
