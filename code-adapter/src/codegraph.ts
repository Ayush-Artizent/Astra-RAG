import './env.js';
import { createRequire } from 'node:module';
import type { CodeGraph as CodeGraphClass } from '@colbymchenry/codegraph';

export type CodeGraph = CodeGraphClass;

interface Library {
  CodeGraph: typeof CodeGraphClass;
}

// The package entry is a CommonJS shim that re-exports a bundled build, so named ESM imports are not
// reliable. Load it once through require; types still come from the package.
let library: Library | undefined;
function load(): Library {
  library ??= createRequire(import.meta.url)('@colbymchenry/codegraph') as Library;
  return library;
}

/** Opens an existing project index read-only. Throws if the project is not initialised. */
export function openReadOnly(projectRoot: string): Promise<CodeGraph> {
  return load().CodeGraph.open(projectRoot, { readOnly: true });
}

/** Whether `projectRoot` holds an initialised CodeGraph index (a `.codegraph/codegraph.db` file). */
export function isInitialized(projectRoot: string): boolean {
  return load().CodeGraph.isInitialized(projectRoot);
}
