"""Runs syncs in the background, one at a time. Inline when not started (tests, scripts), so nothing hangs."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from ...config import SYNC_WORKERS

log = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def start() -> None:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=SYNC_WORKERS, thread_name_prefix="astra-sync")


def stop() -> None:
    """Drop queued work; a run cut short is marked failed by the next startup's sweep."""
    global _executor
    with _lock:
        executor, _executor = _executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def submit(fn, *args) -> None:
    executor = _executor
    if executor is None:
        _guard(fn, *args)
    else:
        executor.submit(_guard, fn, *args)


def _guard(fn, *args) -> None:
    try:
        fn(*args)
    except Exception as exc:  # sync code records its own failures; never log details that could hold secrets
        log.error("Background sync task failed (%s).", type(exc).__name__)
