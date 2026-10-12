"""Ingest worker entrypoint. Autoscaled on queue depth by KEDA in AKS (§3)."""

from __future__ import annotations

import asyncio
import logging

from rag_core.observability import configure_logging
from rag_ingest.config import IngestSettings
from rag_ingest.pipeline import IndexPipeline, PointerConflictError
from rag_ingest.queue import JobQueue

log = logging.getLogger(__name__)


async def run_forever(queue: JobQueue, pipeline: IndexPipeline) -> None:
    while True:
        job = await queue.receive()
        try:
            report = await pipeline.run(job)
            log.info(
                "job done: %s", report, extra={"tenant_id": job.tenant_id, "job_id": job.job_id}
            )
        except PointerConflictError:
            log.info("superseded job dropped", extra={"job_id": job.job_id})
        except Exception:
            # Service Bus: abandon -> retry with backoff -> dead-letter after max deliveries.
            log.exception("job failed", extra={"tenant_id": job.tenant_id, "job_id": job.job_id})


def build_pipeline(settings: IngestSettings) -> IndexPipeline:
    """Wire concrete backends from settings. TODO(ingestion pod): Azure Repos/GitLab clients,
    Postgres state store, Azure AI Search chunk store, Blob snapshots, Azure OpenAI embedder."""
    raise NotImplementedError(
        "Concrete backends not wired yet; see rag_ingest.worker.build_pipeline and docs/runbook.md"
    )


def main() -> None:
    settings = IngestSettings()
    configure_logging(settings.log_level, settings.log_json)
    from rag_ingest.webhook import get_queue

    asyncio.run(run_forever(get_queue(), build_pipeline(settings)))


if __name__ == "__main__":
    main()
