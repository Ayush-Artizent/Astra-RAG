"""Walks project-data/ and turns each supported file into a Document."""
import hashlib
from pathlib import Path

from ...config import MAX_FILE_BYTES, PROJECT_DATA_DIR_NAME, SUPPORTED_EXTENSIONS
from .models import Document, SkippedFile


def load_documents(repo_dir: Path) -> tuple[list[Document], list[SkippedFile]]:
    """Return (documents, skipped). Nothing is dropped silently: skipped carries the reason."""
    root = repo_dir / PROJECT_DATA_DIR_NAME
    docs: list[Document] = []
    skipped: list[SkippedFile] = []
    if not root.is_dir():
        return docs, skipped

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(repo_dir).as_posix()
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        file_type = SUPPORTED_EXTENSIONS.get(path.suffix.lower())
        if file_type is None:
            skipped.append(SkippedFile(rel, f"unsupported file type '{path.suffix or 'none'}'"))
            continue
        size = path.stat().st_size
        if size == 0:
            skipped.append(SkippedFile(rel, "empty file"))
        elif size > MAX_FILE_BYTES:
            skipped.append(SkippedFile(rel, f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"))
        else:
            _load_one(path, rel, file_type, docs, skipped)
    return docs, skipped


def _load_one(path: Path, rel: str, file_type: str, docs: list[Document], skipped: list[SkippedFile]) -> None:
    try:
        data = path.read_bytes()
        text = _docx_to_markdown(path) if file_type == "docx" else _decode(data)
    except Exception as exc:  # a corrupt file must not abort the whole ingestion
        skipped.append(SkippedFile(rel, f"could not read: {type(exc).__name__}"))
        return
    if not text.strip():
        skipped.append(SkippedFile(rel, "no text content"))
        return
    docs.append(Document(rel, file_type, hashlib.sha256(data).hexdigest(), text))


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _docx_to_markdown(path: Path) -> str:
    from markitdown import MarkItDown  # heavy import, only needed for docx

    return MarkItDown().convert(str(path)).text_content
