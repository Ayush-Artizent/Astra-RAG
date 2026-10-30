"""Turns a Document into Chunks and attaches the traceability metadata."""
import hashlib
from pathlib import PurePosixPath

from ...config import PROJECT_DATA_DIR_NAME
from ..sources import adapter_for
from .csv_chunker import chunk_csv
from .doc_meta import DocMeta, extract_metadata, open_items
from .md_chunker import RawChunk, chunk_markdown, document_title
from .models import Chunk, Document, RepoContext

_BREADCRUMB_MAX_CHARS = 200
_META_LINE_MAX_CHARS = 300


def chunk_document(doc: Document, repo: RepoContext) -> tuple[list[Chunk], list[str]]:
    """Return (chunks, warnings) for one document."""
    path = PurePosixPath(doc.path)
    warnings: list[str] = []
    meta = extract_metadata(doc.path, doc.text)
    if doc.file_type == "csv":
        raws, warnings = chunk_csv(doc.text, path.name)
        title = path.name
    else:
        raws = chunk_markdown(doc.text)
        title = document_title(doc.text, meta.fields.get("subject") or path.stem)

    parts = list(path.parent.parts)
    folders_below_root = [p for p in parts if p != PROJECT_DATA_DIR_NAME]
    base = {
        "repo": repo.ref.full_name, "repo_slug": repo.slug, "host": repo.host, "owner": repo.owner,
        "branch": repo.branch, "commit_sha": repo.commit_sha, "path": doc.path, "filename": path.name,
        "folder_parts": parts, "folder_top": folders_below_root[0] if folders_below_root else "",
        "file_type": doc.file_type, "file_hash": doc.file_hash, "title": title,
        "chunk_count": len(raws),
        "doc_type": meta.doc_type, "doc_date": meta.date, "doc_meta": meta.fields,
    }
    chunks = [_build(raw, index, base, doc, repo, title, meta) for index, raw in enumerate(raws)]
    return chunks, warnings


def _build(raw: RawChunk, index: int, base: dict, doc: Document, repo: RepoContext, title: str,
           meta: DocMeta) -> Chunk:
    content_hash = hashlib.sha1(raw.text.encode("utf-8")).hexdigest()
    chunk_id = hashlib.sha1(f"{doc.path}\0{index}\0{content_hash}".encode("utf-8")).hexdigest()
    has_lines = doc.file_type in ("md", "txt") and raw.start is not None
    open_lines = open_items(raw.text)
    payload = {
        **base,
        "has_open_item": bool(open_lines), "open_items": open_lines,
        "chunk_id": chunk_id, "chunk_index": index, "chunk_kind": raw.kind,
        "heading_path": list(raw.heading_path),
        "line_start": raw.start if has_lines else None,
        "line_end": raw.end if has_lines else None,
        "source_url": _source_url(repo, doc.path, raw.start, raw.end) if has_lines
        else _source_url(repo, doc.path, None, None),
        "text": raw.text,
        **raw.extra,
    }
    return Chunk(chunk_id, raw.text, _embed_text(title, raw, meta), payload)


def _embed_text(title: str, raw: RawChunk, meta: DocMeta) -> str:
    breadcrumb = " > ".join([title, *raw.heading_path])[:_BREADCRUMB_MAX_CHARS]
    info = " | ".join([meta.doc_type, *([meta.date] if meta.date else []),
                       *(f"{k}: {v}" for k, v in meta.fields.items() if k != "date")])[:_META_LINE_MAX_CHARS]
    return f"{breadcrumb}\n[{info}]\n\n{raw.text}"


def _source_url(repo: RepoContext, path: str, start: int | None, end: int | None) -> str:
    lines = (start, end) if start is not None else None
    # Pin the link to the commit when known, so it keeps pointing at the text that was indexed.
    return adapter_for(repo.ref).citation_url(path, repo.commit_sha or repo.branch, lines)
