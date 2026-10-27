"""Orchestrates load -> chunk -> embed -> store, and tracks status for the UI."""
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ...config import EMBED_BATCH_SIZE
from ..errors import AppError
from .chunker import chunk_document
from .embedder import Embedder, get_embedder
from .loader import load_documents
from .models import Chunk, RepoContext
from .store import QdrantStore, collection_name


@dataclass
class IngestionStatus:
    state: str = "queued"          # queued | running | done | failed
    commit_sha: str = ""
    collection: str = ""
    files_loaded: int = 0
    files_skipped: list[dict] = field(default_factory=list)
    chunks_total: int = 0
    chunks_stored: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    started_at: str = ""
    finished_at: str = ""


_statuses: dict[str, IngestionStatus] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mark_queued(repo: RepoContext) -> None:
    with _lock:
        _statuses[repo.slug] = IngestionStatus(commit_sha=repo.commit_sha,
                                               collection=collection_name(repo.owner, repo.name))


def get_status(owner: str, name: str) -> dict | None:
    with _lock:
        status = _statuses.get(f"{owner}__{name}")
        return asdict(status) if status else None


def run_ingestion(repo: RepoContext, repo_dir: Path, embedder: Embedder | None = None,
                  store: QdrantStore | None = None) -> None:
    """Never raises: failures are recorded in the status so the UI can show them."""
    with _lock:
        status = _statuses.setdefault(repo.slug, IngestionStatus())
    status.state, status.started_at = "running", _now()
    try:
        _ingest(repo, repo_dir, status, embedder, store)
        status.state = "done"
    except AppError as exc:
        status.state, status.error = "failed", exc.message
    except Exception as exc:
        status.state, status.error = "failed", f"Unexpected error during ingestion ({type(exc).__name__})."
    finally:
        status.finished_at = _now()


def _ingest(repo: RepoContext, repo_dir: Path, status: IngestionStatus,
            embedder: Embedder | None, store: QdrantStore | None) -> None:
    store = store or QdrantStore()
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
    collection = collection_name(repo.owner, repo.name)
    store.recreate(collection, embedder.dense_dim)

    ingested_at = _now()
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i:i + EMBED_BATCH_SIZE]
        dense, sparse = embedder.embed_passages([c.embed_text for c in batch])
        for c in batch:
            c.payload.update(embedding_model=embedder.model_name, embedding_dim=embedder.dense_dim,
                             ingested_at=ingested_at)
        store.upsert(collection, batch, dense, sparse)
        status.chunks_stored += len(batch)


def search(owner: str, name: str, query: str, limit: int = 8, folder_top: str | None = None,
           file_type: str | None = None, embedder: Embedder | None = None,
           store: QdrantStore | None = None) -> list[dict]:
    if not query.strip():
        raise AppError("A search query is required.")
    store = store or QdrantStore()
    store.ping()
    dense, sparse = (embedder or get_embedder()).embed_query(query)
    return store.search(collection_name(owner, name), dense, sparse, limit, folder_top, file_type)
