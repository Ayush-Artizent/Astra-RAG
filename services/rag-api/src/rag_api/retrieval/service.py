"""Retrieval pipeline per call (§7.1):

request -> query understanding -> candidate generation -> fusion -> rerank
        -> dedupe & expand -> context packing -> citations -> trace log -> response
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from time import perf_counter

from rag_api.config import ApiSettings
from rag_api.deps import Backends
from rag_api.retrieval.fusion import dedupe, pack, rrf
from rag_core.interfaces import RedactionError, ScoredHit, SearchFilters, SearchMode
from rag_core.provenance import cite, deep_link
from rag_core.redaction import RegexSecretRedactor
from rag_core.schemas import (
    CallerInfo,
    Chunk,
    RetrievedChunk,
    Scores,
    Timing,
    ToolResponse,
    TraceRecord,
)
from rag_core.tenancy import TenantContext, tenant_scope

_query_redactor = RegexSecretRedactor()


def _traceable(text: str) -> str:
    """Query text as it may be written to the trace. Fails closed: if redaction fails, a marker is
    stored instead of the raw text."""
    try:
        return _query_redactor.redact("<query>", text).text
    except RedactionError:
        return "[REDACTED:REDACTION_FAILED]"


@dataclass(frozen=True)
class RankingProfile:
    """Per-tool knobs. Tune ONLY with rag-eval numbers in hand (§2 principle 7)."""

    lexical_weight: float = 1.0
    vector_weight: float = 1.0


CODE_PROFILE = RankingProfile()
DOCS_PROFILE = RankingProfile(lexical_weight=0.8, vector_weight=1.2)
SIMILAR_REQ_PROFILE = RankingProfile(lexical_weight=0.5, vector_weight=1.5)  # §6.4


@dataclass
class _Stopwatch:
    stages: dict[str, float] = field(default_factory=dict)
    _t: float = field(default_factory=perf_counter)

    def lap(self, name: str) -> None:
        now = perf_counter()
        self.stages[name] = round((now - self._t) * 1000, 2)
        self._t = now


@dataclass
class RetrievalService:
    backends: Backends
    settings: ApiSettings

    async def search(
        self,
        ctx: TenantContext,
        *,
        tool: str,
        query: str,
        filters: SearchFilters,
        k: int,
        token_budget: int | None,
        caller: CallerInfo,
        profile: RankingProfile = CODE_PROFILE,
    ) -> ToolResponse:
        with tenant_scope(ctx):
            return await self._search(ctx, tool, query, filters, k, token_budget, caller, profile)

    async def _search(
        self,
        ctx: TenantContext,
        tool: str,
        query: str,
        filters: SearchFilters,
        k: int,
        token_budget: int | None,
        caller: CallerInfo,
        profile: RankingProfile,
    ) -> ToolResponse:
        b, s = self.backends, self.settings
        trace_id = uuid.uuid4().hex
        sw, t0 = _Stopwatch(), perf_counter()

        # 1. Query understanding. TODO(Phase 2): entity extraction, tenant glossary expansion,
        #    decomposition into sub-queries via ModelProvider.
        rewritten = [query]
        sw.lap("understand")

        # 2. Candidate generation: lexical + vector in parallel, with metadata filters.
        #    TODO(Phase 2): routing step via repo summaries for large tenants.
        qvec = (await b.embedder.embed([query]))[0]
        lex, vec = await asyncio.gather(
            b.chunks.search(SearchMode.LEXICAL, text=query, filters=filters, k=s.candidate_k),
            b.chunks.search(SearchMode.VECTOR, vector=qvec, filters=filters, k=s.candidate_k),
        )
        sw.lap("candidates")

        # 3. Fusion
        fused = rrf([lex, vec], k=s.rrf_k, weights=[profile.lexical_weight, profile.vector_weight])
        sw.lap("fusion")

        # 4. Rerank top ~50-100 to a shortlist
        fused_hits = [ScoredHit(c, sc, SearchMode.VECTOR) for c, sc in fused[: s.candidate_k]]
        reranked = await b.reranker.rerank(query, fused_hits, top_k=k * 3)
        sw.lap("rerank")

        # 5-6. Dedupe (+ expand, Phase 2), then pack into the token budget
        selected = pack(
            dedupe([h.chunk for h in reranked]),
            k=k,
            token_budget=token_budget or s.default_token_budget,
        )
        sw.lap("pack")

        # 7. Cite
        lex_s = {h.chunk.chunk_id: h.score for h in lex}
        vec_s = {h.chunk.chunk_id: h.score for h in vec}
        fus_s = {c.chunk_id: sc for c, sc in fused}
        rr_s = {h.chunk.chunk_id: h.score for h in reranked}
        snapshot = await self._snapshot(selected)
        results = [
            await self._result(
                c,
                Scores(
                    bm25=lex_s.get(c.chunk_id),
                    vector=vec_s.get(c.chunk_id),
                    fused=fus_s.get(c.chunk_id),
                    rerank=rr_s.get(c.chunk_id),
                ),
            )
            for c in selected
        ]
        sw.lap("cite")

        # 8. Trace (redacted query only)
        total = (perf_counter() - t0) * 1000
        await b.traces.record(
            TraceRecord(
                trace_id=trace_id,
                tenant_id=ctx.tenant_id,
                tool=tool,
                caller=caller,
                query_original=_traceable(query),
                query_rewritten=[_traceable(q) for q in rewritten],
                filters={f: v for f, v in asdict(filters).items() if v is not None},
                candidates={
                    "lexical": [(h.chunk.chunk_id, h.score) for h in lex[:50]],
                    "vector": [(h.chunk.chunk_id, h.score) for h in vec[:50]],
                },
                selected=[c.chunk_id for c in selected],
                snapshot=snapshot,
                models={"embedder": b.embedder.model_id, "reranker": b.reranker.model_id},
                latency_ms=total,
            )
        )
        return ToolResponse(
            results=results,
            trace_id=trace_id,
            snapshot=snapshot,
            timing=Timing(total_ms=round(total, 2), stages_ms=sw.stages),
        )

    async def _snapshot(self, chunks: list[Chunk]) -> dict[str, str]:
        out = {}
        for repo in sorted({c.repo for c in chunks}):
            state = await self.backends.state.get_repo(repo)
            if state and state.last_indexed_sha:
                out[repo] = state.last_indexed_sha
        return out

    async def _result(self, c: Chunk, scores: Scores) -> RetrievedChunk:
        state = await self.backends.state.get_repo(c.repo)
        url = (
            deep_link(state.host, state.web_url, c.commit_sha, c.path, c.start_line, c.end_line)
            if state and state.web_url
            else None
        )
        return RetrievedChunk(
            text=c.text,
            header=c.contextual_header(),
            doc_type=c.doc_type,
            trust_tier=c.trust_tier,
            symbol=c.symbol,
            citation=cite(c, scores, url),
        )
