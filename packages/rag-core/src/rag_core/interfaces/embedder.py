"""Embedding model. [DECISION] start with Azure OpenAI; benchmark on own code/docs (§12)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    @property
    def model_id(self) -> str:
        """Stored on every chunk as ``embedding_model`` (e.g. ``text-embedding-3-large@v1``)."""
        ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
