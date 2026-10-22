"""Core data contracts (design doc §5, §7.2, §8).

These models are the contract between ingestion, retrieval, the API and the eval harness.
Provenance is a first-class field, not a feature: every chunk and result carries enough
metadata to be cited, replayed and audited. Change them deliberately and bump
``INDEX_VERSION`` when stored shape or semantics change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Bump whenever chunking, embeddings or index schema change so eval before/after is clean (§10).
INDEX_VERSION = 2  # 2: redaction adds entropy, extra secret formats and PII rules


class DocType(StrEnum):
    CODE = "code"
    BRD = "brd"
    ADR = "adr"
    STANDARD = "standard"
    README = "readme"
    TEST = "test"
    CONFIG = "config"
    SPEC = "spec"


class TrustTier(StrEnum):
    GOLDEN = "golden"
    STANDARD = "standard"


class GitHost(StrEnum):
    AZURE_REPOS = "azure_repos"
    GITLAB = "gitlab"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RedactionInfo(_Frozen):
    count: int = 0
    types: list[str] = Field(default_factory=list)


class Chunk(_Frozen):
    """A semantically whole, self-describing unit of indexed content (§5)."""

    chunk_id: str
    tenant_id: str
    repo: str
    path: str
    commit_sha: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content_hash: str
    text: str
    language: str | None = None
    symbol: str | None = None
    signature: str | None = None
    doc_type: DocType = DocType.CODE
    trust_tier: TrustTier = TrustTier.STANDARD
    heading_path: list[str] | None = None
    is_test: bool = False
    redaction: RedactionInfo = Field(default_factory=RedactionInfo)
    snapshot_uri: str | None = None
    embedding_model: str | None = None
    index_version: int = INDEX_VERSION
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def contextual_header(self) -> str:
        """Header embedded with the text and stored for display (§5)."""
        parts = [
            f"{self.tenant_id}/{self.repo}",
            self.path,
            self.language or "unknown",
            self.symbol or (" > ".join(self.heading_path) if self.heading_path else ""),
            self.signature or "",
            self.doc_type.value,
            self.trust_tier.value,
        ]
        return " | ".join(p for p in parts if p)


class EdgeKind(StrEnum):
    IMPORTS = "imports"
    CALLS = "calls"
    DEPENDS_ON = "depends_on"
    EXPOSES_API = "exposes_api"
    CONSUMES_API = "consumes_api"
    READS_TABLE = "reads_table"
    WRITES_TABLE = "writes_table"
    DOCUMENTS = "documents"


class EdgeSource(StrEnum):
    MANIFEST = "manifest"
    PARSER = "parser"
    HEURISTIC = "heuristic"


class Edge(_Frozen):
    """Dependency-graph edge (§6.3). Static analysis is imprecise, so confidence is explicit."""

    tenant_id: str
    src: str
    dst: str
    kind: EdgeKind
    confidence: float = Field(ge=0.0, le=1.0)
    source: EdgeSource
    commit_sha: str


class Scores(_Frozen):
    bm25: float | None = None
    vector: float | None = None
    fused: float | None = None
    rerank: float | None = None


class Citation(_Frozen):
    """Tier-1 citation attached to every returned chunk (§8). The URL is pinned to the SHA."""

    chunk_id: str
    repo: str
    path: str
    commit_sha: str
    lines: tuple[int, int]
    content_hash: str
    url: str | None = None
    heading_path: list[str] | None = None
    scores: Scores = Field(default_factory=Scores)


class RetrievedChunk(_Frozen):
    text: str
    header: str
    doc_type: DocType
    trust_tier: TrustTier
    symbol: str | None = None
    citation: Citation


class Timing(_Frozen):
    total_ms: float
    stages_ms: dict[str, float] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    """Envelope returned by every agent-facing tool (§7.2), identical across REST, MCP and SDK."""

    results: list[RetrievedChunk]
    trace_id: str
    snapshot: dict[str, str] = Field(
        default_factory=dict, description="repo -> indexed_sha used to answer this call"
    )
    index_version: int = INDEX_VERSION
    timing: Timing
    warnings: list[str] = Field(default_factory=list)


class FeedbackLabel(StrEnum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    MISSING = "missing"


class CallerInfo(_Frozen):
    """Who is calling, for traceability (§8 tier 2). Tenant is NOT here: it comes from auth."""

    platform: str | None = None
    agent_run_id: str | None = None
    ticket_id: str | None = None


class TraceRecord(BaseModel):
    """One record per retrieval call (§8 tier 2). Query text must be redacted before logging."""

    trace_id: str
    tenant_id: str
    tool: str
    caller: CallerInfo
    query_original: str
    query_rewritten: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    candidates: dict[str, list[tuple[str, float]]] = Field(
        default_factory=dict, description="stage -> [(chunk_id, score)]"
    )
    selected: list[str] = Field(default_factory=list)
    snapshot: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)
    index_version: int = INDEX_VERSION
    latency_ms: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RepoState(BaseModel):
    """Per-repo indexing pointer stored in Postgres (§4.1 step 3/9)."""

    tenant_id: str
    repo: str
    host: GitHost
    default_branch: str = "main"
    web_url: str | None = None  # base for SHA-pinned citation deep links
    trust_tier: TrustTier = TrustTier.STANDARD  # golden repos are boosted (§6.4)
    last_indexed_sha: str | None = None
    indexed_at: datetime | None = None
