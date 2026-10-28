import type { JobService } from './service.js';
import type { JobStore } from './store.js';

export interface MaintenanceOptions {
  store: JobStore;
  service: JobService;
  /** Time between passes. 0 means one pass at startup and none after. */
  intervalMs: number;
}

/**
 * Keeps every project checked against its remote. A push webhook can be missed (the adapter was down, a delivery
 * failed), and nothing else would ever notice, so on a schedule a reconcile job is queued for each project.
 */
export class Maintenance {
  private timer: NodeJS.Timeout | undefined;

  constructor(private readonly opts: MaintenanceOptions) {}

  /** Runs a pass now, then repeats every `intervalMs`. The timer does not keep the process alive. */
  start(): void {
    this.tick();
    if (this.opts.intervalMs > 0) {
      this.timer = setInterval(() => this.tick(), this.opts.intervalMs);
      this.timer.unref();
    }
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
  }

  /**
   * Queues a reconcile for every bootstrapped project that is not pruned and has no job queued or running.
   * Pruned projects are left alone until a query wants them. Returns how many checks were queued.
   */
  tick(): number {
    const { store, service } = this.opts;
    let queued = 0;
    for (const project of store.listProjects()) {
      if (project.bootstrappedAt === null || project.prunedAt !== null) continue;
      if (store.activeForProject(project.orgId, project.projectId).length > 0) continue;
      try {
        service.enqueueReconcile(project.orgId, project.projectId);
        queued++;
      } catch {
        // one project failing must not stop the others; the store may also be closing
      }
    }
    return queued;
  }
}
