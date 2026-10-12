"""In-memory backends for local dev and tests. NOT for production.

They honour the same tenancy contract as real stores (tenant from context, never a parameter),
which is what makes the cross-tenant leak tests meaningful.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from rag_core.interfaces.chunk_store import ScoredHit, SearchFilters, SearchMode
from rag_core.schemas import Chunk, Edge, EdgeKind, RepoState
from rag_core.tenancy import TenantIsolationError, assert_same_tenant, require_tenant_id
from rag_core.text import tokenize_identifiers


def _matches(chunk: Chunk, f: SearchFilters) -> bool:
    return (
        (f.repos is None or chunk.repo in f.repos)
        and (f.languages is None or chunk.language in f.languages)
        and (f.doc_types is None or chunk.doc_type in f.doc_types)
        and (f.trust_tiers is None or chunk.trust_tier in f.trust_tiers)
        and (f.path_prefix is None or chunk.path.startswith(f.path_prefix))
        and (f.include_tests or not chunk.is_test)
    )


class MemoryChunkStore:
    def __init__(self) -> None:
        # tenant_id -> chunk_id -> (chunk, vector)
        self._data: dict[str, dict[str, tuple[Chunk, list[float]]]] = defaultdict(dict)

    async def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        tenant = require_tenant_id()
        for chunk, vec in zip(chunks, vectors, strict=True):
            assert_same_tenant(chunk.tenant_id)
            self._data[tenant][chunk.chunk_id] = (chunk, list(vec))

    async def existing_vectors(
        self, content_hashes: Sequence[str], embedding_model: str
    ) -> dict[str, list[float]]:
        tenant = require_tenant_id()
        wanted = set(content_hashes)
        return {
            c.content_hash: v
            for c, v in self._data[tenant].values()
            if c.content_hash in wanted and c.embedding_model == embedding_model
        }

    async def delete_paths(self, repo: str, paths: Sequence[str]) -> int:
        tenant = require_tenant_id()
        doomed = [
            cid for cid, (c, _) in self._data[tenant].items() if c.repo == repo and c.path in paths
        ]
        for cid in doomed:
            del self._data[tenant][cid]
        return len(doomed)

    async def search(
        self,
        mode: SearchMode,
        *,
        text: str | None = None,
        vector: Sequence[float] | None = None,
        filters: SearchFilters,
        k: int,
    ) -> list[ScoredHit]:
        tenant = require_tenant_id()
        rows = [(c, v) for c, v in self._data[tenant].values() if _matches(c, filters)]
        scored: list[ScoredHit] = []
        if mode is SearchMode.LEXICAL and text:
            q = Counter(tokenize_identifiers(text))
            for c, _ in rows:
                d = Counter(tokenize_identifiers(c.contextual_header() + "\n" + c.text))
                s = float(sum(min(q[t], d[t]) for t in q))
                if s > 0:
                    scored.append(ScoredHit(c, s, mode))
        elif mode is SearchMode.VECTOR and vector is not None:
            for c, v in rows:
                scored.append(ScoredHit(c, _cosine(vector, v), mode))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    async def get(self, chunk_ids: Sequence[str]) -> list[Chunk]:
        tenant = require_tenant_id()
        return [self._data[tenant][cid][0] for cid in chunk_ids if cid in self._data[tenant]]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class FakeEmbedder:
    """Deterministic hashing-trick embedder. Lets the full pipeline run with zero cloud deps."""

    def __init__(self, dimensions: int = 256) -> None:
        self._dim = dimensions

    @property
    def model_id(self) -> str:
        return f"fake-hash-{self._dim}@v1"

    @property
    def dimensions(self) -> int:
        return self._dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self._dim
            for tok in tokenize_identifiers(text):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
                vec[h % self._dim] += 1.0 if (h >> 63) & 1 else -1.0
            out.append(vec)
        return out


class PassthroughReranker:
    @property
    def model_id(self) -> str:
        return "passthrough@v0"

    async def rerank(self, query: str, hits: Sequence[ScoredHit], top_k: int) -> list[ScoredHit]:
        return list(hits)[:top_k]


class MemoryGraphStore:
    def __init__(self) -> None:
        self._edges: dict[str, list[Edge]] = defaultdict(list)

    async def upsert_edges(self, repo: str, edges: Sequence[Edge]) -> None:
        tenant = require_tenant_id()
        for e in edges:
            assert_same_tenant(e.tenant_id)
        self._edges[tenant].extend(edges)

    async def delete_for_paths(self, repo: str, paths: Sequence[str]) -> None:
        tenant = require_tenant_id()
        self._edges[tenant] = [e for e in self._edges[tenant] if e.src not in paths]

    async def neighbors(
        self,
        nodes: Sequence[str],
        *,
        depth: int = 1,
        kinds: Sequence[EdgeKind] | None = None,
        reverse: bool = True,
    ) -> list[Edge]:
        tenant = require_tenant_id()
        frontier, seen, out = set(nodes), set(nodes), []
        for _ in range(depth):
            nxt: set[str] = set()
            for e in self._edges[tenant]:
                if kinds and e.kind not in kinds:
                    continue
                here, there = (e.dst, e.src) if reverse else (e.src, e.dst)
                if here in frontier:
                    out.append(e)
                    if there not in seen:
                        nxt.add(there)
            seen |= nxt
            frontier = nxt
        return out


class MemoryBlobStore:
    """Content-addressed snapshot store. Snapshots are kept on delete so old citations resolve."""

    def __init__(self) -> None:
        self._blobs: dict[str, str] = {}

    async def put_snapshot(self, content_hash: str, text: str) -> str:
        uri = f"mem://{require_tenant_id()}/{content_hash}"
        self._blobs.setdefault(uri, text)
        return uri

    async def get_snapshot(self, uri: str) -> str:
        if not uri.startswith(f"mem://{require_tenant_id()}/"):
            raise TenantIsolationError("snapshot belongs to a different tenant")
        return self._blobs[uri]


class MemoryStateStore:
    def __init__(self) -> None:
        self._repos: dict[str, dict[str, RepoState]] = defaultdict(dict)

    def register(self, state: RepoState) -> None:
        assert_same_tenant(state.tenant_id)
        self._repos[state.tenant_id][state.repo] = state

    async def get_repo(self, repo: str) -> RepoState | None:
        return self._repos[require_tenant_id()].get(repo)

    async def list_repos(self) -> list[RepoState]:
        return list(self._repos[require_tenant_id()].values())

    async def commit_pointer(self, repo: str, expected_old_sha: str | None, new_sha: str) -> bool:
        state = self._repos[require_tenant_id()].get(repo)
        if state is None or state.last_indexed_sha != expected_old_sha:
            return False
        state.last_indexed_sha = new_sha
        state.indexed_at = datetime.now(UTC)
        return True
