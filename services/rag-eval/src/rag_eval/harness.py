"""Runs a dataset against a live rag-api and aggregates metrics; gates merges on regression."""

from __future__ import annotations

import statistics
from collections import defaultdict
from time import perf_counter

from pydantic import BaseModel

from astra_rag_sdk import AstraRagClient
from rag_core.schemas import ToolResponse
from rag_eval import metrics
from rag_eval.dataset import EvalCase, Tool

K_VALUES = (5, 10, 20)


class CaseResult(BaseModel):
    id: str
    trace_id: str
    scores: dict[str, float]
    latency_ms: float


class Report(BaseModel):
    index_version: int | None
    n_cases: int
    aggregate: dict[str, float]
    by_tag: dict[str, dict[str, float]]
    cases: list[CaseResult]


async def _call(client: AstraRagClient, case: EvalCase, k: int) -> ToolResponse:
    match case.tool:
        case Tool.SEARCH_CODE:
            return await client.search_code(case.query, k=k, include_tests=True)
        case Tool.SEARCH_DOCS:
            return await client.search_docs(case.query, k=k)
        case Tool.FIND_SIMILAR_REQUIREMENTS:
            return await client.find_similar_requirements(case.query, k=min(k, 20))


def score_case(case: EvalCase, resp: ToolResponse) -> dict[str, float]:
    got = [
        metrics.Retrieved(r.citation.repo, r.citation.path, r.citation.lines) for r in resp.results
    ]
    out = {f"recall@{k}": metrics.recall_at_k(got, case.expected, k) for k in K_VALUES}
    out["mrr"] = metrics.mrr(got, case.expected)
    out["ndcg@10"] = metrics.ndcg_at_k(got, case.expected, 10)
    out["context_precision"] = metrics.context_precision(got[:10], case.expected)
    return out


async def run(client: AstraRagClient, cases: list[EvalCase]) -> Report:
    results: list[CaseResult] = []
    index_version = None
    for case in cases:
        t = perf_counter()
        resp = await _call(client, case, max(K_VALUES))
        results.append(
            CaseResult(
                id=case.id,
                trace_id=resp.trace_id,
                scores=score_case(case, resp),
                latency_ms=(perf_counter() - t) * 1000,
            )
        )
        index_version = resp.index_version
    return Report(
        index_version=index_version,
        n_cases=len(results),
        aggregate=_aggregate(results),
        by_tag=_by_tag(cases, results),
        cases=results,
    )


def _aggregate(results: list[CaseResult]) -> dict[str, float]:
    if not results:
        return {}
    keys = results[0].scores.keys()
    agg = {k: statistics.fmean(r.scores[k] for r in results) for k in keys}
    lat = sorted(r.latency_ms for r in results)
    agg["latency_p50_ms"] = lat[len(lat) // 2]
    agg["latency_p95_ms"] = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    return agg


def _by_tag(cases: list[EvalCase], results: list[CaseResult]) -> dict[str, dict[str, float]]:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for c, r in zip(cases, results, strict=True):
        for tag in c.tags or ["untagged"]:
            groups[tag].append(r)
        groups[f"source:{c.source.value}"].append(r)
    return {tag: _aggregate(rs) for tag, rs in groups.items()}


GATED_METRICS = ("recall@10", "mrr", "ndcg@10")


def gate(baseline: Report, candidate: Report, max_drop: float) -> list[str]:
    """Return regressions (empty list == pass). Used as the CI merge gate (§10 Process)."""
    failures = []
    for m in GATED_METRICS:
        b, c = baseline.aggregate.get(m), candidate.aggregate.get(m)
        if b is not None and c is not None and c < b - max_drop:
            failures.append(f"{m}: {b:.4f} -> {c:.4f} (allowed drop {max_drop})")
    return failures
