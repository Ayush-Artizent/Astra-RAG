"""Walks project-data/ and turns each supported file into a Document."""
import hashlib
from pathlib import Path

from ...config import MAX_FILE_BYTES, PROJECT_DATA_DIR_NAME, SUPPORTED_EXTENSIONS
from .models import Document, SkippedFile

_LINK_REASON = "symbolic link or outside the repository (not followed)"


def load_documents(repo_dir: Path) -> tuple[list[Document], list[SkippedFile]]:
    """Return (documents, skipped). Nothing is dropped silently: skipped carries the reason."""
    root = repo_dir / PROJECT_DATA_DIR_NAME
    docs: list[Document] = []
    skipped: list[SkippedFile] = []
    if not root.is_dir():
        return docs, skipped
    repo_root = repo_dir.resolve()
    if not _is_inside(root, repo_root):
        skipped.append(SkippedFile(PROJECT_DATA_DIR_NAME, _LINK_REASON))
        return docs, skipped

    for folder, dirnames, filenames in root.walk():
        # Prune hidden and linked folders in place so the walk never descends into them.
        for name in sorted(dirnames):
            if name.startswith(".") or _check_link(folder / name, repo_dir, repo_root, skipped):
                dirnames.remove(name)
        for name in filenames:
            path = folder / name
            if not name.startswith(".") and not _check_link(path, repo_dir, repo_root, skipped):
                _load_file(path, path.relative_to(repo_dir).as_posix(), docs, skipped)
    docs.sort(key=lambda d: d.path)
    skipped.sort(key=lambda s: s.path)
    return docs, skipped


def _check_link(path: Path, repo_dir: Path, repo_root: Path, skipped: list[SkippedFile]) -> bool:
    """A hostile repo could link to files outside the clone (e.g. the .env holding PATs)."""
    if path.is_symlink() or path.is_junction() or not _is_inside(path, repo_root):
        skipped.append(SkippedFile(path.relative_to(repo_dir).as_posix(), _LINK_REASON))
        return True
    return False


def _load_file(path: Path, rel: str, docs: list[Document], skipped: list[SkippedFile]) -> None:
    file_type = SUPPORTED_EXTENSIONS.get(path.suffix.lower())
    if file_type is None:
        skipped.append(SkippedFile(rel, f"unsupported file type '{path.suffix or 'none'}'"))
        return
    size = path.stat().st_size
    if size == 0:
        skipped.append(SkippedFile(rel, "empty file"))
    elif size > MAX_FILE_BYTES:
        skipped.append(SkippedFile(rel, f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"))
    else:
        _load_one(path, rel, file_type, docs, skipped)


def _is_inside(path: Path, repo_root: Path) -> bool:
    """True if the real location (links and junctions resolved) is within the clone."""
    try:
        return path.resolve().is_relative_to(repo_root)
    except OSError:
        return False


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
