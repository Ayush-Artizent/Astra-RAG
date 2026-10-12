"""Job queue abstraction. Production: Azure Service Bus with sessions keyed by ``coalesce_key``,
dead-letter queue, and separate low-priority backfill queue (§4.2, §12)."""

from __future__ import annotations

import asyncio
from typing import Protocol

from rag_ingest.jobs import IngestJob


class JobQueue(Protocol):
    async def enqueue(self, job: IngestJob, *, delay_seconds: int = 0) -> None: ...

    async def receive(self) -> IngestJob: ...


class InMemoryQueue:
    """Local dev queue with naive coalescing: newest SHA per repo wins."""

    def __init__(self) -> None:
        self._pending: dict[str, IngestJob] = {}
        self._ready = asyncio.Event()

    async def enqueue(self, job: IngestJob, *, delay_seconds: int = 0) -> None:
        self._pending[job.coalesce_key] = job
        self._ready.set()

    async def receive(self) -> IngestJob:
        while not self._pending:
            self._ready.clear()
            await self._ready.wait()
        key = next(iter(self._pending))
        return self._pending.pop(key)

    def __len__(self) -> int:
        return len(self._pending)
