"""Git host connectors: Azure Repos + GitLab for MVP (§1). Default branch only."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class FileChangeKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True, slots=True)
class FileChange:
    kind: FileChangeKind
    path: str
    old_path: str | None = None  # set for renames


@runtime_checkable
class GitHostClient(Protocol):
    async def default_branch_head(self, repo: str) -> str:
        """Current HEAD SHA of the default branch (used by the reconciler, §4.2)."""
        ...

    async def is_ancestor(self, repo: str, old_sha: str, new_sha: str) -> bool:
        """False on force-push/history rewrite -> fall back to full tree compare."""
        ...

    async def diff(self, repo: str, old_sha: str | None, new_sha: str) -> list[FileChange]:
        """Tree diff; ``old_sha=None`` means full listing (first index / rewrite fallback)."""
        ...

    async def read_file(self, repo: str, sha: str, path: str) -> bytes: ...
