"""Knowledge for a request: one hybrid search on the text, reranked. Nothing is preferred by date, type or folder."""
from dataclasses import dataclass, field

from ...config import KNOWLEDGE_CANDIDATES
from ..errors import AppError
from ..ingestion import pipeline
from .rerank import Reranker, rerank


@dataclass
class Knowledge:
    items: list[dict] = field(default_factory=list)
    status: str = "ok"  # ok | empty | no_index | unavailable: <reason>
    rerank: str = "not_run"


def _item(hit: dict) -> dict:
    return {
        "text": hit.get("text") or "", "file": hit.get("path"), "heading_path": hit.get("heading_path") or [],
        "doc_type": hit.get("doc_type"), "doc_date": hit.get("doc_date"), "doc_meta": hit.get("doc_meta") or {},
        "source_url": hit.get("source_url"), "score": hit.get("score"),
    }


def retrieve(slug: str, text: str, folder: str | None = None, file_type: str | None = None,
             reranker: Reranker | None = None) -> Knowledge:
    """Search failures become a status, so rules and template still reach the caller."""
    try:
        hits = pipeline.search(slug, text, KNOWLEDGE_CANDIDATES, folder, file_type)
    except AppError as exc:
        return Knowledge(status="no_index" if exc.status == 404 else f"unavailable: {exc.message}")
    except Exception as exc:  # embedder or Qdrant failure: type name only, never the reply
        return Knowledge(status=f"unavailable: {type(exc).__name__}")
    items = [_item(h) for h in hits]
    if not items:
        return Knowledge(status="empty")
    items, status = rerank(text, items, reranker)
    return Knowledge(items, "ok", status)
