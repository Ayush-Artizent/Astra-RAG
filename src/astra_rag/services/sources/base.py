"""The port every Git host adapter implements, so the rest of the app never talks to a host directly."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict
from urllib.parse import ParseResult

from ..errors import AppError
from ..repo_ref import RepoRef
from .credentials import Credential


class DirEntry(TypedDict):
    name: str
    type: str  # 'file' | 'dir' (hosts may report others, e.g. 'symlink' or 'submodule')


@dataclass(frozen=True)
class CloneResult:
    path: str
    commit_sha: str
    branch: str


class SourceAdapter(ABC):
    """One repo on one host. Network methods need a credential; `citation_url` and `parse_url` do not."""

    def __init__(self, ref: RepoRef, credential: Credential | None = None):
        self.ref = ref
        self._credential = credential

    def _secret(self) -> str:
        if self._credential is None:
            raise AppError("A personal access token is required.")
        return self._credential.secret()

    @classmethod
    @abstractmethod
    def parse_url(cls, parts: ParseResult, kind: str) -> RepoRef:
        """Turn an already scheme- and host-checked URL into a RepoRef, or raise AppError."""

    @abstractmethod
    def list_dir(self, path: str = "", ref: str | None = None) -> list[DirEntry]:
        """Entries of a folder; "" is the repo root. `ref` is a branch or commit (None = default branch)."""

    @abstractmethod
    def read_file(self, path: str, ref: str | None = None) -> bytes: ...

    @abstractmethod
    def head_sha(self, branch: str) -> str:
        """Commit SHA the branch points to right now."""

    @abstractmethod
    def default_branch(self) -> str: ...

    @abstractmethod
    def clone(self, dest: Path, branch: str | None = None) -> CloneResult:
        """Shallow-clone into `dest` (which must not exist). `branch=None` means the default branch."""

    @abstractmethod
    def is_ancestor(self, base: str, head: str) -> bool:
        """True if commit `base` is reachable from `head` (so `head` is the same or newer)."""

    @abstractmethod
    def citation_url(self, path: str, ref: str, lines: tuple[int, int] | None = None) -> str:
        """Browser link to a file at a commit/branch, optionally highlighting (start, end) lines."""

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Reserved for later: webhooks are not part of the first build."""
        raise AppError("Webhooks are not supported yet.", 501)
