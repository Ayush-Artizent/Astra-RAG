"""Decides where a clone lives in temp_storage/, replaces any earlier copy and removes it after ingestion; the host does the cloning."""
import logging
import os
import shutil
import stat

from ..config import TEMP_STORAGE_DIR
from .sources.base import CloneResult, SourceAdapter

__all__ = ["CloneResult", "clone_repo", "remove_clone", "sweep"]

log = logging.getLogger(__name__)


def clone_repo(adapter: SourceAdapter, branch: str | None = None) -> CloneResult:
    """Clone into temp_storage/<slug>, replacing any earlier clone."""
    TEMP_STORAGE_DIR.mkdir(exist_ok=True)
    target = TEMP_STORAGE_DIR / adapter.ref.slug
    if target.exists():
        shutil.rmtree(target, onexc=_make_writable)
    return adapter.clone(target, branch)


def remove_clone(slug: str) -> None:
    """Delete temp_storage/<slug>. The clone is only an ingestion input, so it never outlives the run; never raises."""
    target = TEMP_STORAGE_DIR / slug
    try:
        if target.exists():
            shutil.rmtree(target, onexc=_make_writable)
    except OSError as exc:
        log.warning("Could not remove the clone of %s (%s).", slug, type(exc).__name__)


def sweep() -> None:
    """Remove every leftover clone (a crash or kill can skip remove_clone). Only call while no run is active."""
    if TEMP_STORAGE_DIR.is_dir():
        for child in TEMP_STORAGE_DIR.iterdir():
            if child.name != ".gitkeep":
                remove_clone(child.name)


def _make_writable(func, path, _exc):
    """Windows marks .git objects read-only; clear that so rmtree can remove them."""
    os.chmod(path, stat.S_IWRITE)
    func(path)
