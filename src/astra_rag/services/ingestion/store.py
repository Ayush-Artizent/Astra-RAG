"""Qdrant access: one collection per repo, dense + sparse named vectors, hybrid search."""
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
    return re.sub(r"[^\w.-]", "_", f"{QDRANT_COLLECTION_PREFIX}__{slug}")


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

    def recreate(self, collection: str, dense_dim: int) -> None:
        """Drop and recreate the collection: a re-ingest replaces the previous copy."""
        if self.client.collection_exists(collection):
            self.client.delete_collection(collection)
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
