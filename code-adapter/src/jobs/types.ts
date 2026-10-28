export type JobType = 'bootstrap' | 'sync' | 'reconcile';
export type JobState = 'queued' | 'running' | 'done' | 'failed' | 'superseded';
/** Phases a job can report. The same list is in the contract. */
export type JobPhase = 'clone' | 'scanning' | 'parsing' | 'resolving' | 'linking' | 'finalizing';

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

/** What the adapter remembers about a project's repo. The credential itself is never stored, only its name. */
export interface ProjectBinding {
  orgId: string;
  projectId: string;
  repoUrl: string;
  branch: string | null;
  credentialsRef: string | null;
  createdAt: number;
  /** Null until the first bootstrap has finished successfully. */
  bootstrappedAt: number | null;
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
