"""Retrieval trace sink (§8 tier 2). MVP: structured log. Phase 2: Postgres/Blob + replay tooling.
Phase 3: append-only WORM, hash-chained."""

from __future__ import annotations

import logging
from typing import Protocol

from rag_core.schemas import FeedbackLabel, TraceRecord

log = logging.getLogger("astra.trace")


class TraceSink(Protocol):
    async def record(self, trace: TraceRecord) -> None: ...

    async def feedback(self, trace_id: str, chunk_id: str | None, label: FeedbackLabel) -> None: ...


class LoggingTraceSink:
    def __init__(self) -> None:
        self.traces: dict[str, TraceRecord] = {}  # local dev only; lets tests and replay inspect

    async def record(self, trace: TraceRecord) -> None:
        # query_original must already be redacted by the caller (privacy note, §8).
        self.traces[trace.trace_id] = trace
        log.info(
            "retrieval",
            extra={
                "tenant_id": trace.tenant_id,
                "tool": trace.tool,
                "trace": trace.trace_id,
                "latency_ms": round(trace.latency_ms, 1),
                "n": len(trace.selected),
            },
        )

    async def feedback(self, trace_id: str, chunk_id: str | None, label: FeedbackLabel) -> None:
        log.info("feedback", extra={"trace": trace_id, "chunk_id": chunk_id, "label": label.value})
