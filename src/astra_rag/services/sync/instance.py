"""One active Astra-RAG process per data directory: it alone runs the scheduler, the worker and startup recovery.

An exclusive OS lock on `<data dir>/astra.lock`, held for the life of the process. The OS drops it when the
process exits or crashes, so a leftover lock file never blocks a restart.
"""
import os
from pathlib import Path

from ..errors import AppError
from ..registry import db

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class InstanceLock:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db.current_path().parent / "astra.lock"
        self._file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise AppError(f"Another Astra-RAG instance is already running on this data directory ({self.path}). "
                           "Only one instance is supported: stop the other one first.", 500) from None
        self._file = handle

    def release(self) -> None:
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
