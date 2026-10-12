"""Agent-facing tools (§7.2). Small, composable, fast calls with citations in every response.

Every route takes the tenant from :func:`rag_api.auth.authenticate`; request bodies have no
tenant field (``extra="forbid"`` rejects one if sent).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from rag_api.auth import Tenant
from rag_api.config import ApiSettings
from rag_api.deps import Backends, get_backends, get_settings
from rag_api.retrieval.service import (
    CODE_PROFILE,
    DOCS_PROFILE,
    SIMILAR_REQ_PROFILE,
    RetrievalService,
)
from rag_core.api_models import (
    ExpandContextRequest,
    FeedbackRequest,
    FindImpactedRequest,
    FindImpactedResponse,
    FindSimilarRequirementsRequest,
    GetFileRequest,
    GetSymbolRequest,
    ImpactEdge,
    ListReposRequest,
    ListReposResponse,
    RepoInfo,
    SearchCodeRequest,
    SearchDocsRequest,
)
from rag_core.interfaces import SearchFilters
from rag_core.schemas import DocType, ToolResponse
from rag_core.tenancy import tenant_scope

router = APIRouter(prefix="/v1/tools", tags=["tools"])

BackendsDep = Annotated[Backends, Depends(get_backends)]
SettingsDep = Annotated[ApiSettings, Depends(get_settings)]

_DOC_TYPES = [DocType.BRD, DocType.ADR, DocType.STANDARD, DocType.README, DocType.SPEC]


def _svc(b: Backends, s: ApiSettings) -> RetrievalService:
    return RetrievalService(b, s)


@router.post("/search_code", response_model=ToolResponse)
async def search_code(
    req: SearchCodeRequest, ctx: Tenant, b: BackendsDep, s: SettingsDep
) -> ToolResponse:
    """Hybrid code search."""
    filters = SearchFilters(
        repos=req.repos,
        languages=req.languages,
        doc_types=[DocType.CODE, DocType.CONFIG, DocType.TEST]
        if req.include_tests
        else [DocType.CODE, DocType.CONFIG],
        include_tests=req.include_tests,
    )
    return await _svc(b, s).search(
        ctx,
        tool="search_code",
        query=req.query,
        filters=filters,
        k=req.k,
        token_budget=req.token_budget,
        caller=req.caller,
        profile=CODE_PROFILE,
    )


@router.post("/search_docs", response_model=ToolResponse)
async def search_docs(
    req: SearchDocsRequest, ctx: Tenant, b: BackendsDep, s: SettingsDep
) -> ToolResponse:
    """Docs, BRDs, ADRs, standards."""
    filters = SearchFilters(doc_types=req.doc_types or _DOC_TYPES)
    return await _svc(b, s).search(
        ctx,
        tool="search_docs",
        query=req.query,
        filters=filters,
        k=req.k,
        token_budget=req.token_budget,
        caller=req.caller,
        profile=DOCS_PROFILE,
    )


@router.post("/find_similar_requirements", response_model=ToolResponse)
async def find_similar_requirements(
    req: FindSimilarRequirementsRequest, ctx: Tenant, b: BackendsDep, s: SettingsDep
) -> ToolResponse:
    """Past BRDs/specs similar to a new requirement (semantic-weighted ranking profile, §6.4)."""
    filters = SearchFilters(doc_types=[DocType.BRD, DocType.SPEC])
    return await _svc(b, s).search(
        ctx,
        tool="find_similar_requirements",
        query=req.text,
        filters=filters,
        k=req.k,
        token_budget=None,
        caller=req.caller,
        profile=SIMILAR_REQ_PROFILE,
    )


@router.post("/find_impacted", response_model=FindImpactedResponse)
async def find_impacted(
    req: FindImpactedRequest, ctx: Tenant, b: BackendsDep
) -> FindImpactedResponse:
    """Impact analysis over the dependency graph. MVP: manifest-level edges only (§13)."""
    if not req.entities:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "entities required in MVP")
    with tenant_scope(ctx):
        edges = await b.graph.neighbors(req.entities, depth=req.depth, kinds=req.kinds)
    return FindImpactedResponse(
        edges=[
            ImpactEdge(
                src=e.src, dst=e.dst, kind=e.kind, confidence=e.confidence, source=e.source.value
            )
            for e in edges
        ],
        trace_id=uuid.uuid4().hex,
        warnings=[
            "MVP: manifest-level dependency edges only; symbol-level calls arrive in Phase 2"
        ],
    )


@router.post("/list_repos", response_model=ListReposResponse)
async def list_repos(req: ListReposRequest, ctx: Tenant, b: BackendsDep) -> ListReposResponse:
    """Navigation. Repo summaries (§6.2) arrive in Phase 2."""
    with tenant_scope(ctx):
        repos = await b.state.list_repos()
    q = (req.query or "").lower()
    return ListReposResponse(
        repos=[
            RepoInfo(
                repo=r.repo,
                indexed_sha=r.last_indexed_sha,
                indexed_at=r.indexed_at.isoformat() if r.indexed_at else None,
                trust_tier=r.trust_tier.value,
            )
            for r in repos
            if q in r.repo.lower()
        ],
        trace_id=uuid.uuid4().hex,
    )


@router.post("/submit_feedback", status_code=status.HTTP_202_ACCEPTED)
async def submit_feedback(req: FeedbackRequest, ctx: Tenant, b: BackendsDep) -> dict[str, str]:
    """Closes the improvement loop: feeds eval labels (§10)."""
    # TODO(platform pod): verify trace_id belongs to ctx.tenant_id once traces are persisted.
    await b.traces.feedback(req.trace_id, req.chunk_id, req.label)
    return {"status": "accepted"}


def _not_yet(name: str) -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"{name} lands later in Phase 1/2")


@router.post("/get_file")
async def get_file(req: GetFileRequest, ctx: Tenant) -> None:
    """Exact fetch at the indexed SHA. TODO: read from git host cache / Blob snapshots."""
    raise _not_yet("get_file")


@router.post("/get_symbol")
async def get_symbol(req: GetSymbolRequest, ctx: Tenant) -> None:
    raise _not_yet("get_symbol")


@router.post("/expand_context")
async def expand_context(req: ExpandContextRequest, ctx: Tenant) -> None:
    raise _not_yet("expand_context")
