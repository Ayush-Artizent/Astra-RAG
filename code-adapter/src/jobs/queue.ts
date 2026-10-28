import { scrubText } from './scrub.js';
import type { JobStore } from './store.js';
import type { Executor, JobRow, JobType } from './types.js';

export interface QueueOptions {
  store: JobStore;
  executors: Partial<Record<JobType, Executor>>;
  /** Jobs running at once, across all projects. */
  maxConcurrent: number;
  /** Bootstraps running at once. A Django-sized bootstrap needs about 2 GB, so the default is 1. */
  maxBootstraps?: number;
  /** Called after a job has been marked done or failed. */
  onSettled?: (job: JobRow, outcome: 'done' | 'failed') => void;
  now?: () => number;
}

interface Running {
  job: JobRow;
  controller: AbortController;
  done: Promise<void>;
}

/**
 * Runs queued jobs under three rules: one job per project at a time, at most `maxBootstraps` bootstraps at
 * once, and at most `maxConcurrent` jobs overall. Jobs start in the order they were created.
 */
export class JobQueue {
  private readonly running = new Map<string, Running>();
  private stopped = false;
  private readonly maxBootstraps: number;
  private readonly now: () => number;

  constructor(private readonly opts: QueueOptions) {
    this.maxBootstraps = opts.maxBootstraps ?? 1;
    this.now = opts.now ?? Date.now;
  }

  /** Marks jobs a previous process left running as failed, then starts whatever is queued. */
  start(): void {
    this.opts.store.failInterruptedJobs('The adapter restarted while this job was running');
    this.kick();
  }

  /** Starts every queued job that is allowed to run now. Safe to call at any time. */
  kick(): void {
    if (this.stopped) return;
    for (const job of this.opts.store.queued()) {
      if (this.running.size >= this.opts.maxConcurrent) return;
      if (this.projectBusy(job)) continue;
      if (job.type === 'bootstrap' && this.runningOfType('bootstrap') >= this.maxBootstraps) continue;
      this.launch(job);
    }
  }

  isRunning(jobId: string): boolean {
    return this.running.has(jobId);
  }

  /** Stops accepting work, aborts running jobs and waits for them to finish. Queued jobs stay queued. */
  async stop(): Promise<void> {
    this.stopped = true;
    for (const r of this.running.values()) r.controller.abort();
    await Promise.allSettled([...this.running.values()].map((r) => r.done));
  }

  /** Resolves when nothing is running and nothing runnable is queued. For tests and shutdown. */
  async idle(): Promise<void> {
    for (;;) {
      this.kick();
      if (this.running.size === 0) return;
      await Promise.allSettled([...this.running.values()].map((r) => r.done));
    }
  }

  private projectBusy(job: JobRow): boolean {
    for (const r of this.running.values()) {
      if (r.job.orgId === job.orgId && r.job.projectId === job.projectId) return true;
    }
    return false;
  }

  private runningOfType(type: JobType): number {
    let n = 0;
    for (const r of this.running.values()) if (r.job.type === type) n++;
    return n;
  }

  private launch(queued: JobRow): void {
    const { store } = this.opts;
    store.update(queued.id, { state: 'running', startedAt: this.now(), phase: null, progress: null });
    const job = store.get(queued.id) as JobRow;
    const controller = new AbortController();
    const entry: Running = { job, controller, done: Promise.resolve() };
    // Registered before the executor starts, so a synchronous executor cannot be scheduled twice.
    this.running.set(job.id, entry);
    entry.done = this.run(job, controller).finally(() => {
      this.running.delete(job.id);
      this.kick();
    });
  }

  private async run(job: JobRow, controller: AbortController): Promise<void> {
    const { store } = this.opts;
    let outcome: 'done' | 'failed' = 'done';
    try {
      const executor = this.opts.executors[job.type];
      if (!executor) throw new Error(`No executor for ${job.type} jobs`);
      const project = store.getProject(job.orgId, job.projectId);
      if (!project) throw new Error('The project has no repo binding');

      const result = await executor({
        job,
        project,
        signal: controller.signal,
        update: (patch) => store.update(job.id, { phase: patch.phase, progress: patch.progress }),
      });
      store.update(job.id, {
        state: 'done',
        finishedAt: this.now(),
        progress: 1,
        files: result?.files ?? null,
        symbols: result?.symbols ?? null,
        edges: result?.edges ?? null,
      });
    } catch (e) {
      outcome = 'failed';
      const message = controller.signal.aborted ? 'Cancelled: the adapter is shutting down' : e instanceof Error ? e.message : String(e);
      store.update(job.id, { state: 'failed', finishedAt: this.now(), error: scrubText(message) });
    }
    try {
      this.opts.onSettled?.(store.get(job.id) as JobRow, outcome);
    } catch {
      // A failing hook must not leave the job looking unfinished.
    }
  }
}
