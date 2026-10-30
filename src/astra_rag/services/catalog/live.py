"""SourceReader over a host adapter: live reads of one branch, pinned to the commit seen first."""
from ...config import MAX_CATALOG_FILE_BYTES
from ..errors import AppError
from ..sources.base import SourceAdapter


class AdapterReader:
    """One reader per request. The branch head is looked up once and every read uses that commit,
    so the catalog is a consistent snapshot and its `head_sha` is exactly what was read."""

    def __init__(self, adapter: SourceAdapter, branch: str):
        self.adapter, self.branch = adapter, branch
        self._sha: str | None = None

    def head_sha(self) -> str:
        if self._sha is None:
            self._sha = self.adapter.head_sha(self.branch)
        return self._sha

    def list_dir(self, path: str) -> list[dict]:
        try:
            return list(self.adapter.list_dir(path, ref=self.head_sha()))
        except AppError as exc:
            if exc.status == 404 and path:  # a folder that is not there is simply empty
                return []
            raise

    def read_file(self, path: str) -> str | None:
        try:
            data = self.adapter.read_file(path, ref=self.head_sha())
        except AppError as exc:
            if exc.status == 404:
                return None
            raise
        if len(data) > MAX_CATALOG_FILE_BYTES:
            return None
        return data.decode("utf-8", errors="replace")
