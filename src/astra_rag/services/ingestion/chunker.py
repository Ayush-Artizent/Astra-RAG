"""Turns a Document into Chunks and attaches the traceability metadata."""
import hashlib
from pathlib import PurePosixPath
from urllib.parse import quote

from ...config import PROJECT_DATA_DIR_NAME
from .csv_chunker import chunk_csv
from .md_chunker import RawChunk, chunk_markdown, document_title
from .models import Chunk, Document, RepoContext

_BREADCRUMB_MAX_CHARS = 200


def chunk_document(doc: Document, repo: RepoContext) -> tuple[list[Chunk], list[str]]:
    """Return (chunks, warnings) for one document."""
    path = PurePosixPath(doc.path)
    warnings: list[str] = []
    if doc.file_type == "csv":
        raws, warnings = chunk_csv(doc.text, path.name)
        title = path.name
    else:
        raws = chunk_markdown(doc.text)
        title = document_title(doc.text, path.stem)

    parts = list(path.parent.parts)
    folders_below_root = [p for p in parts if p != PROJECT_DATA_DIR_NAME]
    base = {
        "repo": repo.ref.full_name, "repo_slug": repo.slug, "host": repo.host, "owner": repo.owner,
        "branch": repo.branch, "commit_sha": repo.commit_sha, "path": doc.path, "filename": path.name,
        "folder_parts": parts, "folder_top": folders_below_root[0] if folders_below_root else "",
        "file_type": doc.file_type, "file_hash": doc.file_hash, "title": title,
        "chunk_count": len(raws),
    }
    chunks = [_build(raw, index, base, doc, repo, title) for index, raw in enumerate(raws)]
    return chunks, warnings


def _build(raw: RawChunk, index: int, base: dict, doc: Document, repo: RepoContext, title: str) -> Chunk:
    content_hash = hashlib.sha1(raw.text.encode("utf-8")).hexdigest()
    chunk_id = hashlib.sha1(f"{doc.path}\0{index}\0{content_hash}".encode("utf-8")).hexdigest()
    has_lines = doc.file_type in ("md", "txt") and raw.start is not None
    payload = {
        **base,
        "chunk_id": chunk_id, "chunk_index": index, "chunk_kind": raw.kind,
        "heading_path": list(raw.heading_path),
        "line_start": raw.start if has_lines else None,
        "line_end": raw.end if has_lines else None,
        "source_url": _source_url(repo, doc.path, raw.start, raw.end) if has_lines
        else _source_url(repo, doc.path, None, None),
        "text": raw.text,
        **raw.extra,
    }
    return Chunk(chunk_id, raw.text, _embed_text(title, raw), payload)


def _embed_text(title: str, raw: RawChunk) -> str:
    breadcrumb = " > ".join([title, *raw.heading_path])[:_BREADCRUMB_MAX_CHARS]
    return f"{breadcrumb}\n\n{raw.text}"


def _source_url(repo: RepoContext, path: str, start: int | None, end: int | None) -> str:
    ref = repo.commit_sha or repo.branch
    url = f"https://{repo.host}/{repo.ref.full_name}/blob/{quote(ref)}/{quote(path)}"
    return f"{url}#L{start}-L{end}" if start is not None else url
