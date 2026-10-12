from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel

from rag_core.api_models import (
    FeedbackRequest,
    FindImpactedRequest,
    FindImpactedResponse,
    FindSimilarRequirementsRequest,
    ListReposRequest,
    ListReposResponse,
    SearchCodeRequest,
    SearchDocsRequest,
)
from rag_core.schemas import CallerInfo, DocType, EdgeKind, FeedbackLabel, ToolResponse


class AstraRagError(RuntimeError):
    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(f"Astra RAG API error {status}: {detail}")
        self.status = status
        self.detail = detail


class AstraRagClient:
    """Async client. Pass ``caller`` so every retrieval is traceable to an agent run / ticket.

    >>> async with AstraRagClient("https://rag.example.com", token="...") as rag:
    ...     resp = await rag.search_code("refund eligibility rules", k=5)
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        caller: CallerInfo | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._caller = caller or CallerInfo()
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, et: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post[T: BaseModel](self, tool: str, req: BaseModel, out: type[T]) -> T:
        r = await self._http.post(
            f"/v1/tools/{tool}", json=req.model_dump(mode="json", exclude_none=True)
        )
        if r.status_code >= 400:
            raise AstraRagError(r.status_code, r.json().get("detail") if r.content else None)
        return out.model_validate(r.json())

    async def search_code(
        self,
        query: str,
        *,
        repos: list[str] | None = None,
        languages: list[str] | None = None,
        k: int = 10,
        include_tests: bool = False,
        token_budget: int | None = None,
    ) -> ToolResponse:
        req = SearchCodeRequest(
            query=query,
            repos=repos,
            languages=languages,
            k=k,
            include_tests=include_tests,
            token_budget=token_budget,
            caller=self._caller,
        )
        return await self._post("search_code", req, ToolResponse)

    async def search_docs(
        self,
        query: str,
        *,
        doc_types: list[DocType] | None = None,
        k: int = 10,
        token_budget: int | None = None,
    ) -> ToolResponse:
        req = SearchDocsRequest(
            query=query, doc_types=doc_types, k=k, token_budget=token_budget, caller=self._caller
        )
        return await self._post("search_docs", req, ToolResponse)

    async def find_similar_requirements(self, text: str, *, k: int = 5) -> ToolResponse:
        req = FindSimilarRequirementsRequest(text=text, k=k, caller=self._caller)
        return await self._post("find_similar_requirements", req, ToolResponse)

    async def find_impacted(
        self, entities: list[str], *, depth: int = 2, kinds: list[EdgeKind] | None = None
    ) -> FindImpactedResponse:
        req = FindImpactedRequest(entities=entities, depth=depth, kinds=kinds, caller=self._caller)
        return await self._post("find_impacted", req, FindImpactedResponse)

    async def list_repos(self, query: str | None = None) -> ListReposResponse:
        return await self._post(
            "list_repos", ListReposRequest(query=query, caller=self._caller), ListReposResponse
        )

    async def submit_feedback(
        self,
        trace_id: str,
        label: FeedbackLabel,
        *,
        chunk_id: str | None = None,
        comment: str | None = None,
    ) -> None:
        req = FeedbackRequest(
            trace_id=trace_id, chunk_id=chunk_id, label=label, comment=comment, caller=self._caller
        )
        r = await self._http.post("/v1/tools/submit_feedback", json=req.model_dump(mode="json"))
        if r.status_code >= 400:
            raise AstraRagError(r.status_code, r.text)
