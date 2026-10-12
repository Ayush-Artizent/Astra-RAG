"""Retrieval metrics (§10): recall@k, MRR, nDCG@k, context precision."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from rag_eval.dataset import ExpectedSource


@dataclass(frozen=True, slots=True)
class Retrieved:
    repo: str
    path: str
    lines: tuple[int, int]


def match(r: Retrieved, e: ExpectedSource) -> bool:
    if (r.repo, r.path) != (e.repo, e.path):
        return False
    if e.lines is None:
        return True
    return r.lines[0] <= e.lines[1] and e.lines[0] <= r.lines[1]


def _first_match(r: Retrieved, expected: Sequence[ExpectedSource]) -> int | None:
    return next((i for i, e in enumerate(expected) if match(r, e)), None)


def recall_at_k(results: Sequence[Retrieved], expected: Sequence[ExpectedSource], k: int) -> float:
    if not expected:
        return 0.0
    found = {i for r in results[:k] if (i := _first_match(r, expected)) is not None}
    return len(found) / len(expected)


def mrr(results: Sequence[Retrieved], expected: Sequence[ExpectedSource]) -> float:
    for rank, r in enumerate(results, start=1):
        if _first_match(r, expected) is not None:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(results: Sequence[Retrieved], expected: Sequence[ExpectedSource], k: int) -> float:
    credited: set[int] = set()
    dcg = 0.0
    for rank, r in enumerate(results[:k], start=1):
        i = _first_match(r, expected)
        if i is not None and i not in credited:  # each expected source credited once
            credited.add(i)
            dcg += (2 ** expected[i].grade - 1) / math.log2(rank + 1)
    ideal = sorted((e.grade for e in expected), reverse=True)[:k]
    idcg = sum((2**g - 1) / math.log2(rank + 1) for rank, g in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def context_precision(results: Sequence[Retrieved], expected: Sequence[ExpectedSource]) -> float:
    """Fraction of returned context that is relevant ("noisy context" problem)."""
    if not results:
        return 0.0
    return sum(1 for r in results if _first_match(r, expected) is not None) / len(results)
