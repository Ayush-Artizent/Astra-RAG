"""Code/dependency graph for impact analysis (§6.3). Default: Postgres node/edge tables."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from rag_core.schemas import Edge, EdgeKind


@runtime_checkable
class GraphStore(Protocol):
    async def upsert_edges(self, repo: str, edges: Sequence[Edge]) -> None: ...

    async def delete_for_paths(self, repo: str, paths: Sequence[str]) -> None: ...

    async def neighbors(
        self,
        nodes: Sequence[str],
        *,
        depth: int = 1,
        kinds: Sequence[EdgeKind] | None = None,
        reverse: bool = True,
    ) -> list[Edge]:
        """``reverse=True`` walks *dependents* (what is impacted if ``nodes`` change)."""
        ...
