"""Local dense (bge) + sparse (BM25) embeddings via fastembed. services/local_models.py downloads them at startup."""
import os
from functools import lru_cache
from typing import Protocol

from ...config import DENSE_DIM, DENSE_MODEL, EMBED_BATCH_SIZE, FASTEMBED_CACHE_DIR, SPARSE_MODEL
from .. import local_models

Sparse = tuple[list[int], list[float]]


class Embedder(Protocol):
    dense_dim: int
    model_name: str

    def embed_passages(self, texts: list[str]) -> tuple[list[list[float]], list[Sparse]]: ...
    def embed_query(self, text: str) -> tuple[list[float], Sparse]: ...


class FastEmbedEmbedder:
    dense_dim = DENSE_DIM
    model_name = DENSE_MODEL

    def __init__(self) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from fastembed import SparseTextEmbedding, TextEmbedding

        FASTEMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = str(FASTEMBED_CACHE_DIR)
        self._dense = TextEmbedding(DENSE_MODEL, cache_dir=cache)
        self._sparse = SparseTextEmbedding(SPARSE_MODEL, cache_dir=cache)

    def embed_passages(self, texts: list[str]) -> tuple[list[list[float]], list[Sparse]]:
        dense = [v.tolist() for v in self._dense.embed(texts, batch_size=EMBED_BATCH_SIZE)]
        sparse = [(s.indices.tolist(), s.values.tolist()) for s in self._sparse.embed(texts)]
        return dense, sparse

    def embed_query(self, text: str) -> tuple[list[float], Sparse]:
        dense = next(iter(self._dense.query_embed(text))).tolist()
        s = next(iter(self._sparse.query_embed(text)))
        return dense, (s.indices.tolist(), s.values.tolist())


@lru_cache(maxsize=1)
def _load_embedder() -> Embedder:
    return FastEmbedEmbedder()


def get_embedder() -> Embedder:
    local_models.require_ready("embedder")  # never download inside a request or a run
    return _load_embedder()
