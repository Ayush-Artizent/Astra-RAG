"""Request models for the agent-facing tools (§7.2). One shape for REST, MCP and SDK.

Note there is no ``tenant_id`` anywhere here: tenant comes from the credential (§9).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rag_core.schemas import CallerInfo, DocType, EdgeKind, FeedbackLabel


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caller: CallerInfo = Field(default_factory=CallerInfo)


class SearchCodeRequest(_Req):
    query: str = Field(min_length=1, max_length=8000)
    repos: list[str] | None = None
    languages: list[str] | None = None
    include_tests: bool = False  # tests are down-weighted for "what does it do" queries (§5)
    k: int = Field(default=10, ge=1, le=50)
    token_budget: int | None = Field(default=None, ge=256)


class SearchDocsRequest(_Req):
    query: str = Field(min_length=1, max_length=8000)
    doc_types: list[DocType] | None = None
    k: int = Field(default=10, ge=1, le=50)
    token_budget: int | None = Field(default=None, ge=256)


class FindSimilarRequirementsRequest(_Req):
    text: str = Field(min_length=1, max_length=32000)
    k: int = Field(default=5, ge=1, le=20)


class FindImpactedRequest(_Req):
    entities: list[str] | None = None
    query: str | None = None
    depth: int = Field(default=2, ge=1, le=4)
    kinds: list[EdgeKind] | None = None


class GetFileRequest(_Req):
    repo: str
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class GetSymbolRequest(_Req):
    repo: str
    symbol: str


class ExpandContextRequest(_Req):
    chunk_id: str
    mode: str = Field(default="neighbors", pattern="^(parent|neighbors|callers|callees)$")


class ListReposRequest(_Req):
    query: str | None = None


class FeedbackRequest(_Req):
    trace_id: str
    chunk_id: str | None = None
    label: FeedbackLabel
    comment: str | None = Field(default=None, max_length=2000)


class RepoInfo(BaseModel):
    repo: str
    indexed_sha: str | None
    indexed_at: str | None
    trust_tier: str
    summary: str | None = None


class ListReposResponse(BaseModel):
    repos: list[RepoInfo]
    trace_id: str


class ImpactEdge(BaseModel):
    src: str
    dst: str
    kind: EdgeKind
    confidence: float
    source: str


class FindImpactedResponse(BaseModel):
    edges: list[ImpactEdge]
    trace_id: str
    snapshot: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
