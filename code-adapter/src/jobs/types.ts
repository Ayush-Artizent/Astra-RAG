import type { JobStore } from './store.js';

export type JobType = 'bootstrap' | 'sync' | 'reconcile';
export type JobState = 'queued' | 'running' | 'done' | 'failed' | 'superseded';
/** Phases a job can report. The same list is in the contract. */
export type JobPhase =
  | 'clone'
  | 'checking'
  | 'scanning'
  | 'parsing'
  | 'resolving'
  | 'linking'
  | 'maintenance'
  | 'finalizing';

export interface JobRow {
  id: string;
  orgId: string;
  projectId: string;
  type: JobType;
  state: JobState;
  commitSha: string | null;
  phase: JobPhase | null;
  progress: number | null;
  error: string | null;
  /** What a finished job did, in a sentence. Mostly useful for reconcile: "up to date", "queued a sync", "pruned". */
  detail: string | null;
  createdAt: number;
  startedAt: number | null;
  finishedAt: number | null;
  files: number | null;
  symbols: number | null;
  edges: number | null;
  coalescedInto: string | null;
  idempotencyKey: string | null;
  requestHash: string | null;
}

/** What the adapter remembers about a project. The credential itself is never stored, only its name. */
export interface ProjectBinding {
  orgId: string;
  projectId: string;
  repoUrl: string;
  branch: string | null;
  credentialsRef: string | null;
  createdAt: number;
  /** Null until the first bootstrap has finished successfully. */
  bootstrappedAt: number | null;
  /** The newest commit known to exist on the remote, from a sync request or a reconcile check. */
  remoteHead: string | null;
  remoteCheckedAt: number | null;
  /** When the index first fell behind `remoteHead`. Null while it is up to date. */
  behindSince: number | null;
  /** Last time a query used the project, or a job finished for it. Drives idle pruning. */
  lastUsedAt: number | null;
  /** Set when idle pruning deleted the folder. The next query rebuilds it. */
  prunedAt: number | null;
  diskTreeBytes: number | null;
  diskGitBytes: number | null;
  diskIndexBytes: number | null;
  diskMeasuredAt: number | null;
}

/** A validated job request. */
export type JobRequest =
  | { type: 'bootstrap'; repoUrl: string; credentialsRef: string | null; branch: string | null }
  | { type: 'sync'; commitSha: string }
  | { type: 'reconcile' };

export interface NewJob {
  orgId: string;
  projectId: string;
  type: JobType;
  commitSha?: string | null;
  idempotencyKey?: string | null;
  requestHash?: string | null;
}

export interface JobResult {
  files?: number;
  symbols?: number;
  edges?: number;
  detail?: string;
}

export interface JobContext {
  job: JobRow;
  project: ProjectBinding;
  /** Reports progress. Phase and progress are stored and shown by GET job. */
  update(patch: { phase?: JobPhase; progress?: number | null }): void;
  /** Aborted when the adapter shuts down. Executors must stop their child processes when it fires. */
  signal: AbortSignal;
}

export type Executor = (ctx: JobContext) => Promise<JobResult | void>;

/** What the executors need from the job system that is created after them. */
export interface ExecutorDeps {
  store: JobStore;
  /** Queues a sync to `commitSha` for a bootstrapped project, folding older queued syncs into it. */
  enqueueSync(orgId: string, projectId: string, commitSha: string): JobRow;
  /** Queues a rebuild of a project that already has a repo binding. */
  enqueueBootstrap(orgId: string, projectId: string): JobRow;
}
