"""Pure ranking helpers (§7.1 steps 3, 5, 6). Kept side-effect free so rag-eval can sweep them."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from rag_core.interfaces import ScoredHit
from rag_core.schemas import Chunk


def rrf(
    ranked_lists: Sequence[Sequence[ScoredHit]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[Chunk, float]]:
    """Reciprocal Rank Fusion. ``weights`` are tunable per tool."""
    weights = weights or [1.0] * len(ranked_lists)
    scores: dict[str, float] = defaultdict(float)
    chunks: dict[str, Chunk] = {}
    for w, hits in zip(weights, ranked_lists, strict=True):
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk.chunk_id] += w / (k + rank)
            chunks[hit.chunk.chunk_id] = hit.chunk
    return sorted(((chunks[cid], s) for cid, s in scores.items()), key=lambda x: x[1], reverse=True)


def dedupe(chunks: Sequence[Chunk]) -> list[Chunk]:
    """Drop exact duplicates (same content across repos/forks) and overlapping windows of a file."""
    seen_hashes: set[str] = set()
    taken: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    out = []
    for c in chunks:
        if c.content_hash in seen_hashes:
            continue
        spans = taken[(c.repo, c.path)]
        if any(_overlap(c.start_line, c.end_line, s, e) > 0.5 for s, e in spans):
            continue
        seen_hashes.add(c.content_hash)
        spans.append((c.start_line, c.end_line))
        out.append(c)
    return out


def _overlap(a1: int, a2: int, b1: int, b2: int) -> float:
    inter = max(0, min(a2, b2) - max(a1, b1) + 1)
    return inter / max(1, min(a2 - a1 + 1, b2 - b1 + 1))


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def pack(
    chunks: Sequence[Chunk], *, k: int, token_budget: int, max_per_file: int = 3
) -> list[Chunk]:
    """Fit into the caller's token budget, preferring diversity across files and repos."""
    out: list[Chunk] = []
    per_file: dict[tuple[str, str], int] = defaultdict(int)
    used = 0
    deferred: list[Chunk] = []
    for c in chunks:
        key = (c.repo, c.path)
        if per_file[key] >= max_per_file:
            deferred.append(c)
            continue
        cost = estimate_tokens(c.text)
        if used + cost > token_budget:
            continue
        out.append(c)
        per_file[key] += 1
        used += cost
        if len(out) >= k:
            return out
    for c in deferred:  # backfill with same-file chunks only if budget remains
        cost = estimate_tokens(c.text)
        if len(out) >= k or used + cost > token_budget:
            break
        out.append(c)
        used += cost
    return out
