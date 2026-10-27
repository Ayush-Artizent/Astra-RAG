import path from 'node:path';
import { ProblemError } from './errors.js';
import { ID_PATTERN } from './envelope.js';

const refuse = (detail: string) => new ProblemError(422, 'path_refused', 'Path refused', detail);

/**
 * The one place that turns an org and project from the envelope into a directory.
 * Nothing else may build a project path.
 */
export function projectDir(dataDir: string, orgId: string, projectId: string): string {
  if (!ID_PATTERN.test(orgId)) throw refuse('Invalid org id');
  if (!ID_PATTERN.test(projectId)) throw refuse('Invalid project id');
  const root = path.resolve(dataDir);
  const dir = path.resolve(root, orgId, projectId);
  const rel = path.relative(root, dir);
  if (rel.startsWith('..') || path.isAbsolute(rel) || rel.split(path.sep).length !== 2) {
    throw refuse('Path escapes the data directory');
  }
  return dir;
}

/**
 * Validates a caller supplied relative path prefix (for example `path_prefix`).
 * Returns it normalised with forward slashes. Never returns an absolute or parent-relative path.
 */
export function safeRelativePrefix(input: string): string {
  if (input.includes('\0')) throw refuse('Invalid path prefix');
  const normalised = input.replace(/\\/g, '/');
  if (/^([A-Za-z]:|\/)/.test(normalised)) throw refuse('Path prefix must be relative');
  const segments = normalised.split('/').filter((s) => s !== '' && s !== '.');
  if (segments.some((s) => s === '..')) throw refuse('Path prefix must not contain ..');
  return segments.join('/');
}
