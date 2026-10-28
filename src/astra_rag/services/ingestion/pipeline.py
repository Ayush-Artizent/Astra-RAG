"""Orchestrates load -> chunk -> embed -> store, and records progress on the run in the registry.

Each run builds a new version collection and only then switches the repo's alias to it, so a failed or
running rebuild never empties search.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ...config import EMBED_BATCH_SIZE
from ..errors import AppError
from ..registry import runs
from .chunker import chunk_document
from .embedder import Embedder, get_embedder
from .loader import load_documents
from .models import Chunk, RepoContext
from .store import QdrantStore, collection_name, version_name


@dataclass
class IngestionStatus:
    """Progress counters for one run; written to the run's row in the registry as they change."""
    files_loaded: int = 0
    files_skipped: list[dict] = field(default_factory=list)
    chunks_total: int = 0
    chunks_stored: int = 0
    warnings: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_ingestion(run_id: int, repo: RepoContext, repo_dir: Path, embedder: Embedder | None = None,
                  store: QdrantStore | None = None) -> None:
    """Never raises: the outcome is recorded on the run so the UI can show it."""
    status = IngestionStatus()
    store = store or QdrantStore()
    state, error = "failed", ""
    try:
        runs.update_run(run_id, state="running", started_at=_now())
        _ingest(run_id, repo, repo_dir, status, embedder, store)
        state = "done"
    except AppError as exc:
        error = exc.message
    except Exception as exc:
        error = f"Unexpected error during ingestion ({type(exc).__name__})."
    if state == "failed":
        try:  # drop the half-built version; the alias still serves the last good one
            store.delete_version(repo.slug, version_name(repo.slug, run_id))
        except Exception:
            pass  # Qdrant is unreachable; the next sync or startup recovery removes it
    try:
        runs.finish_run(run_id, state, error=error, **asdict(status))
    except Exception:
        pass  # the registry is unreachable; the startup sweep marks the run failed


def _ingest(run_id: int, repo: RepoContext, repo_dir: Path, status: IngestionStatus,
            embedder: Embedder | None, store: QdrantStore) -> None:
    def save(**extra) -> None:
        runs.update_run(run_id, **asdict(status), **extra)

    store.ping()

    docs, skipped = load_documents(repo_dir)
    status.files_loaded = len(docs)
    status.files_skipped = [asdict(s) for s in skipped]

    chunks: list[Chunk] = []
    for doc in docs:
        doc_chunks, warnings = chunk_document(doc, repo)
        chunks.extend(doc_chunks)
        status.warnings += [f"{doc.path}: {w}" for w in warnings]
    status.chunks_total = len(chunks)
    if not chunks:
        status.warnings.append("No indexable content found in project-data/.")

    embedder = embedder or get_embedder()
    collection = version_name(repo.slug, run_id)
    save(collection=collection)
    store.create(collection, embedder.dense_dim)

    ingested_at = _now()
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i:i + EMBED_BATCH_SIZE]
        dense, sparse = embedder.embed_passages([c.embed_text for c in batch])
        for c in batch:
            c.payload.update(embedding_model=embedder.model_name, embedding_dim=embedder.dense_dim,
                             ingested_at=ingested_at)
        store.upsert(collection, batch, dense, sparse)
        status.chunks_stored += len(batch)
        save()

    stored = store.count(collection)
    if stored != len(chunks):
        raise AppError(f"Index check failed: {stored} of {len(chunks)} chunks were stored.", 500)
    store.swap_alias(collection_name(repo.slug), collection)
    try:
        store.drop_versions(repo.slug, keep=collection)
    except Exception:
        status.warnings.append("Older index versions could not be removed yet; the next sync removes them.")


def search(slug: str, query: str, limit: int = 8, folder_top: str | None = None,
           file_type: str | None = None, embedder: Embedder | None = None,
           store: QdrantStore | None = None) -> list[dict]:
    if not query.strip():
        raise AppError("A search query is required.")
    store = store or QdrantStore()
    store.ping()
    dense, sparse = (embedder or get_embedder()).embed_query(query)
    return store.search(collection_name(slug), dense, sparse, limit, folder_top, file_type)
