"""Qdrant access: per repo, versioned collections behind an alias; dense + sparse named vectors, hybrid search.

Search uses the alias (`collection_name`). A rebuild fills a new version, then the alias is switched in one call,
so search never sees an empty or half-built index.
"""
import re
import uuid

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from ...config import QDRANT_API_KEY, QDRANT_COLLECTION_PREFIX, QDRANT_URL
from ..errors import AppError
from .embedder import Sparse
from .models import Chunk

_NAMESPACE = uuid.UUID("6f1c3a52-9b0e-4d5e-8a57-4c1d2f7a9e10")
_INDEXED_FIELDS = ("path", "folder_top", "file_type", "file_hash", "commit_sha")


def collection_name(slug: str) -> str:
    """The alias search reads through (before P5 this was a real collection)."""
    return re.sub(r"[^\w.-]", "_", f"{QDRANT_COLLECTION_PREFIX}__{slug}")


def version_name(slug: str, run_id: int) -> str:
    """One build of a repo's index: `astra_v<run id>__<slug>`, which can't be mistaken for another repo's alias."""
    return f"{QDRANT_COLLECTION_PREFIX}_v{run_id}{collection_name(slug)[len(QDRANT_COLLECTION_PREFIX):]}"


def version_run_id(slug: str, name: str | None) -> int | None:
    """The run that built a version collection, or None if `name` is not one of this repo's versions."""
    match = re.fullmatch(rf"{QDRANT_COLLECTION_PREFIX}_v(\d+)__(.+)", name or "")
    if match and match[2] == collection_name(slug)[len(QDRANT_COLLECTION_PREFIX) + 2:]:
        return int(match[1])
    return None


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, chunk_id))


class QdrantStore:
    def __init__(self, client: QdrantClient | None = None) -> None:
        self.client = client or QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30)

    def ping(self) -> None:
        try:
            self.client.get_collections()
        except Exception:
            raise AppError("Could not reach Qdrant. Is it running? (docker compose up -d qdrant)", 503) from None

    def create(self, collection: str, dense_dim: int) -> None:
        """Create a new (version) collection; existing ones are never dropped here."""
        self.client.create_collection(
            collection,
            vectors_config={"dense": models.VectorParams(size=dense_dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for field in _INDEXED_FIELDS:
            self.client.create_payload_index(collection, field, models.PayloadSchemaType.KEYWORD)

    def upsert(self, collection: str, chunks: list[Chunk], dense: list[list[float]], sparse: list[Sparse]) -> None:
        points = [
            models.PointStruct(
                id=point_id(c.chunk_id),
                vector={"dense": d, "sparse": models.SparseVector(indices=s[0], values=s[1])},
                payload=c.payload,
            )
            for c, d, s in zip(chunks, dense, sparse)
        ]
        self.client.upsert(collection, points, wait=True)

    def count(self, collection: str) -> int:
        return self.client.count(collection, exact=True).count

    def collections(self) -> set[str]:
        """Real collection names (aliases are not included)."""
        return {c.name for c in self.client.get_collections().collections}

    def alias_target(self, alias: str) -> str | None:
        return next((a.collection_name for a in self.client.get_aliases().aliases if a.alias_name == alias), None)

    def swap_alias(self, alias: str, collection: str) -> None:
        """Point the alias at `collection` in one atomic call."""
        if alias in self.collections():
            # Built before P5 as a real collection: it must go before the alias can take its name.
            self.client.delete_collection(alias)
        operations = []
        if self.alias_target(alias) is not None:
            operations.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias)))
        operations.append(models.CreateAliasOperation(
            create_alias=models.CreateAlias(collection_name=collection, alias_name=alias)))
        self.client.update_collection_aliases(change_aliases_operations=operations)

    def versions(self, slug: str) -> list[str]:
        return sorted(n for n in self.collections() if version_run_id(slug, n) is not None)

    def delete_version(self, slug: str, name: str) -> bool:
        """Delete one of this repo's version collections, never the one the alias serves. True if deleted."""
        if version_run_id(slug, name) is None:
            raise ValueError(f"Not a version collection of {slug}: {name}")
        if name == self.alias_target(collection_name(slug)) or name not in self.collections():
            return False
        self.client.delete_collection(name)
        return True

    def drop_versions(self, slug: str, keep: str | None = None) -> list[str]:
        """Delete every other version (old builds, half-built leftovers). Returns the names deleted."""
        return [n for n in self.versions(slug) if n != keep and self.delete_version(slug, n)]

    def search(self, collection: str, dense: list[float], sparse: Sparse, limit: int = 8,
               folder_top: str | None = None, file_type: str | None = None) -> list[dict]:
        """Hybrid (dense + BM25) search fused with RRF. Returns payloads plus a score."""
        flt = _filter(folder_top, file_type)
        prefetch_limit = max(limit * 3, 20)
        try:
            result = self.client.query_points(
                collection,
                prefetch=[
                    models.Prefetch(query=dense, using="dense", limit=prefetch_limit, filter=flt),
                    models.Prefetch(query=models.SparseVector(indices=sparse[0], values=sparse[1]),
                                    using="sparse", limit=prefetch_limit, filter=flt),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit, with_payload=True,
            )
        except UnexpectedResponse as exc:
            if exc.status_code == 404:
                raise AppError("No index exists for this repository yet.", 404) from None
            raise
        return [{**(p.payload or {}), "score": p.score} for p in result.points]


def _filter(folder_top: str | None, file_type: str | None) -> models.Filter | None:
    must = []
    if folder_top:
        must.append(models.FieldCondition(key="folder_top", match=models.MatchValue(value=folder_top)))
    if file_type:
        must.append(models.FieldCondition(key="file_type", match=models.MatchValue(value=file_type)))
    return models.Filter(must=must) if must else None
