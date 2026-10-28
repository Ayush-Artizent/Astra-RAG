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
}

const int = (value: string | undefined, fallback: number): number => {
  const n = Number(value);
  return value !== undefined && Number.isInteger(n) && n > 0 ? n : fallback;
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
  };
}
