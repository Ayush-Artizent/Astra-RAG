"""Index state (``last_indexed_sha`` per repo), stored in Postgres (§4.1)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from rag_core.schemas import RepoState


@runtime_checkable
class StateStore(Protocol):
    async def get_repo(self, repo: str) -> RepoState | None: ...

    async def list_repos(self) -> list[RepoState]: ...

    async def commit_pointer(self, repo: str, expected_old_sha: str | None, new_sha: str) -> bool:
        """Compare-and-set ``last_indexed_sha``. Returns False if another job moved it first."""
        ...
