"""Backend wiring. Selects implementations by name from settings (§2 principle 6)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rag_api.config import ApiSettings
from rag_api.trace import LoggingTraceSink, TraceSink
from rag_core.interfaces import ChunkStore, Embedder, GraphStore, Reranker, StateStore
from rag_core.memory import (
    FakeEmbedder,
    MemoryChunkStore,
    MemoryGraphStore,
    MemoryStateStore,
    PassthroughReranker,
)


@dataclass
class Backends:
    chunks: ChunkStore
    graph: GraphStore
    state: StateStore
    embedder: Embedder
    reranker: Reranker
    traces: TraceSink


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()


def build_backends(settings: ApiSettings) -> Backends:
    def unsupported(kind: str, name: str) -> NotImplementedError:
        return NotImplementedError(f"{kind}={name!r} not implemented yet (memory only in template)")

    if settings.chunk_store != "memory":
        raise unsupported("chunk_store", settings.chunk_store)  # TODO: AzureSearchChunkStore
    if settings.embedder != "fake":
        raise unsupported("embedder", settings.embedder)  # TODO: AzureOpenAIEmbedder
    if settings.reranker != "passthrough":
        raise unsupported("reranker", settings.reranker)  # TODO: semantic ranker / cross-encoder
    return Backends(
        chunks=MemoryChunkStore(),
        graph=MemoryGraphStore(),
        state=MemoryStateStore(),
        embedder=FakeEmbedder(),
        reranker=PassthroughReranker(),
        traces=LoggingTraceSink(),
    )


@lru_cache
def get_backends() -> Backends:
    return build_backends(get_settings())
