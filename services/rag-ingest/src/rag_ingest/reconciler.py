"""Reconciler (§4.2): webhooks DO get lost, so this is mandatory.

Nightly + on-demand: for every repo, compare host default-branch HEAD with ``last_indexed_sha``
and enqueue a job for any drift.
"""

from __future__ import annotations

from rag_core.interfaces import GitHostClient, StateStore
from rag_core.tenancy import TenantContext, tenant_scope
from rag_ingest.jobs import IngestJob, JobReason
from rag_ingest.queue import JobQueue


async def reconcile_tenant(
    tenant_id: str, state: StateStore, git: GitHostClient, queue: JobQueue
) -> list[IngestJob]:
    enqueued = []
    with tenant_scope(TenantContext(tenant_id, principal="rag-reconciler")):
        for repo in await state.list_repos():
            head = await git.default_branch_head(repo.repo)
            if head != repo.last_indexed_sha:
                job = IngestJob(
                    tenant_id=tenant_id,
                    repo=repo.repo,
                    host=repo.host,
                    new_sha=head,
                    reason=JobReason.RECONCILE,
                )
                await queue.enqueue(job)
                enqueued.append(job)
    return enqueued


def main() -> None:
    # TODO(ingestion pod): iterate tenants from Postgres, wire real clients; run as AKS CronJob.
    raise NotImplementedError("reconciler wiring pending; see reconcile_tenant()")
