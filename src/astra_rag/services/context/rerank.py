"""Cross-encoder rerank of search hits, with a time budget. Failures keep the search order and say so."""
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Protocol

from ...config import FASTEMBED_CACHE_DIR, RERANK_MODEL, RERANK_TIMEOUT_SECONDS


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class FastEmbedReranker:
    def __init__(self) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        FASTEMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._model = TextCrossEncoder(RERANK_MODEL, cache_dir=str(FASTEMBED_CACHE_DIR))

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, texts)]


@lru_cache(maxsize=1)
def get_reranker() -> Reranker:
    return FastEmbedReranker()


# One worker: a call that outlives its timeout keeps running, so later calls queue behind it instead of piling up.
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rerank")


def _score(reranker: Reranker | None, query: str, texts: list[str]) -> list[float]:
    scores = (reranker or get_reranker()).score(query, texts)
    if len(scores) != len(texts):
        raise ValueError("score count mismatch")
    return scores


def rerank(query: str, items: list[dict], reranker: Reranker | None = None) -> tuple[list[dict], str]:
    """(items best first with `rerank_score`, status). Status is `ok`, `not_run` or `skipped: <reason>`."""
    if len(items) < 2:
        return items, "not_run"
    try:
        scores = _pool.submit(_score, reranker, query, [i["text"] for i in items]).result(RERANK_TIMEOUT_SECONDS)
    except TimeoutError:
        return items, "skipped: timeout"
    except Exception as exc:  # model download or load failure: never fail the request over it
        return items, f"skipped: {type(exc).__name__}"
    ranked = sorted(zip(scores, items), key=lambda pair: -pair[0])
    return [{**item, "rerank_score": score} for score, item in ranked], "ok"
