"""Plain data types shared by the ingestion steps."""
from dataclasses import dataclass, field

from ..repo_ref import RepoRef


@dataclass(frozen=True)
class RepoContext:
    """Identifies exactly which version of which repo the chunks came from."""
    ref: RepoRef
    branch: str
    commit_sha: str

    @property
    def host(self) -> str:
        return self.ref.host

    @property
    def owner(self) -> str:
        return self.ref.owner

    @property
    def name(self) -> str:
        return self.ref.name

    @property
    def slug(self) -> str:
        return self.ref.slug


@dataclass
class Document:
    path: str          # repo-relative, forward slashes, e.g. project-data/hr/leave.md
    file_type: str     # md | txt | csv | docx
    file_hash: str     # sha256 of the original bytes
    text: str          # decoded text (docx already converted to markdown)


@dataclass
class Chunk:
    chunk_id: str
    text: str          # stored in the payload and shown to the LLM
    embed_text: str    # text that is embedded (breadcrumb + text)
    payload: dict = field(default_factory=dict)


@dataclass
class SkippedFile:
    path: str
    reason: str
