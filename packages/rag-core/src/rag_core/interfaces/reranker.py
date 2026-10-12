"""Cross-encoder rerank of top ~50-100 to top-k: biggest lever on noisy context (§7.1 step 4)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from rag_core.interfaces.chunk_store import ScoredHit


@runtime_checkable
class Reranker(Protocol):
    @property
    def model_id(self) -> str: ...

    async def rerank(
        self, query: str, hits: Sequence[ScoredHit], top_k: int
    ) -> list[ScoredHit]: ...
