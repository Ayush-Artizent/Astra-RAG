"""Decides where a clone lives in temp_storage/ and replaces any earlier copy; the host does the cloning."""
import os
import shutil
import stat

from ..config import TEMP_STORAGE_DIR
from .sources.base import CloneResult, SourceAdapter

__all__ = ["CloneResult", "clone_repo"]


def clone_repo(adapter: SourceAdapter, branch: str | None = None) -> CloneResult:
    """Clone into temp_storage/<slug>, replacing any earlier clone."""
    TEMP_STORAGE_DIR.mkdir(exist_ok=True)
    target = TEMP_STORAGE_DIR / adapter.ref.slug
    if target.exists():
        shutil.rmtree(target, onexc=_make_writable)
    return adapter.clone(target, branch)


def _make_writable(func, path, _exc):
    """Windows marks .git objects read-only; clear that so rmtree can remove them."""
    os.chmod(path, stat.S_IWRITE)
    func(path)
