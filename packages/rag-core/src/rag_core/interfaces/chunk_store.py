"""Hybrid chunk index (§6.1). Default: Azure AI Search. [DECISION] alt: pgvector + OpenSearch."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from rag_core.schemas import Chunk, DocType, TrustTier


class SearchMode(StrEnum):
    LEXICAL = "lexical"  # BM25 with identifier-aware analyzer
    VECTOR = "vector"


@dataclass(frozen=True, slots=True)
class SearchFilters:
    repos: Sequence[str] | None = None
    languages: Sequence[str] | None = None
    doc_types: Sequence[DocType] | None = None
    trust_tiers: Sequence[TrustTier] | None = None
    path_prefix: str | None = None
    include_tests: bool = True


@dataclass(frozen=True, slots=True)
class ScoredHit:
    chunk: Chunk
    score: float
    mode: SearchMode
    extra: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class ChunkStore(Protocol):
    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None: ...

    async def existing_vectors(
        self, content_hashes: Sequence[str], embedding_model: str
    ) -> dict[str, list[float]]:
        """Vectors already stored for these content hashes (any repo in the tenant) under the
        same embedding model. Hits are reused instead of re-embedded (§4.1 step 7, §11)."""
        ...

    async def delete_paths(self, repo: str, paths: Sequence[str]) -> int: ...

    async def search(
        self,
        mode: SearchMode,
        *,
        text: str | None = None,
        vector: Sequence[float] | None = None,
        filters: SearchFilters,
        k: int,
    ) -> list[ScoredHit]: ...

    async def get(self, chunk_ids: Sequence[str]) -> list[Chunk]: ...
