import './env.js';
import path from 'node:path';

export interface Config {
  port: number;
  host: string;
  dataDir: string;
  envelopeKey: string;
  maxEnvelopeLifetimeSeconds: number;
  clockSkewSeconds: number;
  /** Jobs (bootstrap, sync) running at once across all projects. */
  maxConcurrentJobs: number;
  /** Hosts a repo may be cloned from. Empty means any public host. */
  allowedRepoHosts: string[];
  /** Accept `file://` repo URLs. Tests and local development only; never in a deployment. */
  allowFileRepos: boolean;
  /** Longest a bootstrap may run. Django, 3,000 files, took about 7 minutes. */
  bootstrapTimeoutMs: number;
  /** Longest a sync may run. Django took about 1 minute whatever the change size. */
  syncTimeoutMs: number;
  /** How often every project is checked against its remote (reconcile). 0 turns the schedule off. */
  reconcileIntervalMs: number;
  /**
   * Delete a project's folder after this many days without a query, and rebuild it on the next query.
   * 0 (the default) never deletes anything: the retention period is a decision for the reviewer.
   */
  idleProjectDays: number;
  /** Run `git gc` on a project when its loose git objects pass this many kilobytes... */
  gcLooseKb: number;
  /**
   * ...or this many objects. Both are checked because `git count-objects` reports tiny objects as 0 KB, so a size
   * limit alone would never fire for a small repo.
   */
  gcLooseObjects: number;
}

const int = (value: string | undefined, fallback: number): number => {
  const n = Number(value);
  return value !== undefined && Number.isInteger(n) && n > 0 ? n : fallback;
};

/** Like `int`, but 0 is a valid value (it switches a feature off). */
const nonNegative = (value: string | undefined, fallback: number): number => {
  const n = Number(value);
  return value !== undefined && value.trim() !== '' && Number.isInteger(n) && n >= 0 ? n : fallback;
};

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const envelopeKey = env.ASTRA_ENVELOPE_KEY;
  if (!envelopeKey || envelopeKey.length < 16) {
    throw new Error('ASTRA_ENVELOPE_KEY must be set to a secret of at least 16 characters');
  }
  return {
    port: Number(env.PORT ?? 8091),
    host: env.HOST ?? '127.0.0.1',
    dataDir: path.resolve(env.ASTRA_DATA_DIR ?? './data'),
    envelopeKey,
    maxEnvelopeLifetimeSeconds: 300,
    clockSkewSeconds: 30,
    maxConcurrentJobs: int(env.ASTRA_MAX_CONCURRENT_JOBS, 2),
    allowedRepoHosts: (env.ASTRA_ALLOWED_REPO_HOSTS ?? '')
      .split(',')
      .map((h) => h.trim().toLowerCase())
      .filter((h) => h.length > 0),
    allowFileRepos: env.ASTRA_ALLOW_FILE_REPOS === '1',
    bootstrapTimeoutMs: int(env.ASTRA_BOOTSTRAP_TIMEOUT_MS, 60 * 60_000),
    syncTimeoutMs: int(env.ASTRA_SYNC_TIMEOUT_MS, 20 * 60_000),
    reconcileIntervalMs: nonNegative(env.ASTRA_RECONCILE_INTERVAL_MS, 10 * 60_000),
    idleProjectDays: nonNegative(env.ASTRA_IDLE_PROJECT_DAYS, 0),
    gcLooseKb: int(env.ASTRA_GC_LOOSE_KB, 20_000),
    gcLooseObjects: int(env.ASTRA_GC_LOOSE_OBJECTS, 500),
  };
}
