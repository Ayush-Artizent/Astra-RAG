"""Plain data types shared by the ingestion steps."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RepoContext:
    """Identifies exactly which version of which repo the chunks came from."""
    host: str
    owner: str
    name: str
    branch: str
    commit_sha: str

    @property
    def slug(self) -> str:
        return f"{self.owner}__{self.name}"


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
