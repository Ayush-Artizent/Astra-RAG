"""SourceReader over a local clone. Never follows symlinks or paths that resolve outside the clone."""
from pathlib import Path

from ...config import MAX_CATALOG_FILE_BYTES


class LocalCloneReader:
    def __init__(self, root: Path, head_sha: str):
        self.root = root.resolve()
        self._head_sha = head_sha

    def head_sha(self) -> str:
        return self._head_sha

    def _safe(self, path: str) -> Path | None:
        target = self.root / path if path else self.root
        if target.is_symlink() or not target.resolve().is_relative_to(self.root):
            return None
        return target

    def list_dir(self, path: str) -> list[dict]:
        folder = self._safe(path)
        if folder is None or not folder.is_dir():
            return []
        entries = []
        for child in sorted(folder.iterdir()):
            if child.name == ".git" or child.is_symlink():
                continue
            if child.is_dir():
                entries.append({"name": child.name, "type": "dir"})
            elif child.is_file():
                entries.append({"name": child.name, "type": "file"})
        return entries

    def read_file(self, path: str) -> str | None:
        target = self._safe(path)
        if target is None or not target.is_file() or target.stat().st_size > MAX_CATALOG_FILE_BYTES:
            return None
        return target.read_text(encoding="utf-8", errors="replace")
