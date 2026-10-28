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
  /** Called after a job has been marked done or failed, including jobs found interrupted at startup. */
  onSettled?: (job: JobRow, outcome: 'done' | 'failed') => void;
  /**
   * Undoes what a job that was cut off by a restart left behind (a half-made clone, a checkout ahead of its
   * index). Runs before any queued job starts.
   */
  recover?: (job: JobRow) => Promise<void>;
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

  /**
   * Marks jobs a previous process left running as failed, cleans up after them, then starts whatever is queued.
   * Cleanup finishes first, so a queued job never meets a half-made folder.
   */
  async start(): Promise<void> {
    const interrupted = this.opts.store.failInterruptedJobs('The adapter restarted while this job was running');
    for (const job of interrupted) {
      try {
        await this.opts.recover?.(job);
      } catch (e) {
        const why = e instanceof Error ? e.message : String(e);
        this.opts.store.update(job.id, { error: scrubText(`The adapter restarted while this job was running (cleanup failed: ${why})`) });
      }
      try {
        this.opts.onSettled?.(this.opts.store.get(job.id) as JobRow, 'failed');
      } catch {
        // a failing hook must not stop startup
      }
    }
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

  /**
   * Stops accepting work, aborts running jobs and waits for them to finish. Queued jobs stay queued.
   * A job that ignores the abort signal is given `timeoutMs`, then recorded as failed so shutdown cannot hang.
   */
  async stop(timeoutMs = 10_000): Promise<void> {
    this.stopped = true;
    for (const r of this.running.values()) r.controller.abort();
    const finished = Promise.allSettled([...this.running.values()].map((r) => r.done)).then(() => 'finished' as const);
    let timer: NodeJS.Timeout | undefined;
    const expired = new Promise<'expired'>((resolve) => {
      timer = setTimeout(() => resolve('expired'), timeoutMs);
    });
    const outcome = await Promise.race([finished, expired]);
    clearTimeout(timer);
    if (outcome === 'expired') {
      for (const r of this.running.values()) {
        this.write(() =>
          this.opts.store.update(r.job.id, {
            state: 'failed',
            finishedAt: this.now(),
            error: 'Cancelled: the adapter is shutting down, and the job did not stop in time',
          }),
        );
      }
    }
  }

  /** Store writes after shutdown began can fail because the store is closed. That is expected, not an error. */
  private write(fn: () => void): void {
    try {
      fn();
    } catch (e) {
      if (!this.stopped) throw e;
    }
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
    entry.done = this.run(job, controller)
      // run() records its own failures. Anything that still escapes (the database itself failing) must not
      // become an unhandled rejection that takes the process down.
      .catch(() => undefined)
      .finally(() => {
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
        update: (patch) => this.write(() => store.update(job.id, { phase: patch.phase, progress: patch.progress })),
      });
      this.write(() =>
        store.update(job.id, {
          state: 'done',
          finishedAt: this.now(),
          progress: 1,
          files: result?.files ?? null,
          symbols: result?.symbols ?? null,
          edges: result?.edges ?? null,
          detail: result?.detail ?? null,
        }),
      );
    } catch (e) {
      outcome = 'failed';
      const message = controller.signal.aborted ? 'Cancelled: the adapter is shutting down' : e instanceof Error ? e.message : String(e);
      this.write(() => store.update(job.id, { state: 'failed', finishedAt: this.now(), error: scrubText(message) }));
    }
    try {
      this.write(() => this.opts.onSettled?.(store.get(job.id) as JobRow, outcome));
    } catch {
      // A failing hook must not leave the job looking unfinished.
    }
  }
}
