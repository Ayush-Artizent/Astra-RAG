"""Nightly sync: a daemon thread that checks every repo at SYNC_DAILY_AT (UTC), plus a catch-up at startup."""
import logging
import re
import threading
from datetime import datetime, timedelta, timezone

from ...config import SYNC_CATCHUP_HOURS, SYNC_DAILY_AT
from ..errors import AppError
from ..registry import repos, runs
from . import reconcile
from .service import request_sync

log = logging.getLogger(__name__)
_thread: threading.Thread | None = None
_stop = threading.Event()


def parse_daily_at(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        raise ValueError(f"ASTRA_SYNC_DAILY_AT must be HH:MM (24-hour, UTC), got {value!r}.")
    return int(match[1]), int(match[2])


def next_run_at(now: datetime, daily_at: str = SYNC_DAILY_AT) -> datetime:
    """The next time of day `daily_at` strictly after `now` (both UTC)."""
    hour, minute = parse_daily_at(daily_at)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def schedule() -> dict:
    """What the UI shows about automatic checks."""
    running = _thread is not None and _thread.is_alive()
    upcoming = next_run_at(datetime.now(timezone.utc)).isoformat(timespec="seconds") if running else None
    return {"enabled": running, "daily_at_utc": SYNC_DAILY_AT, "next_check_at": upcoming}


def start() -> None:
    global _thread
    parse_daily_at(SYNC_DAILY_AT)  # a bad setting fails at startup, not at 2 am
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="astra-sync-scheduler", daemon=True)
    _thread.start()


def stop(timeout: float = 5) -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout)
    _thread = None


def _loop() -> None:
    run_pass(repos.due_slugs(SYNC_CATCHUP_HOURS), "catch_up", _stop)
    while not _stop.wait(_seconds_until_next()):
        reconcile.run()
        run_pass(repos.all_slugs(), "nightly", _stop)


def _seconds_until_next() -> float:
    now = datetime.now(timezone.utc)
    return (next_run_at(now) - now).total_seconds()


def run_pass(slugs: list[str], triggered_by: str, stop: threading.Event | None = None) -> None:
    """Check each repo; one repo's failure is recorded on it and never stops the others."""
    for slug in slugs:
        if stop is not None and stop.is_set():
            return
        try:
            _, force = runs.take_pending(slug)  # a rebuild asked for by recovery
            request_sync(slug, triggered_by, force)
        except AppError as exc:
            log.warning("Scheduled sync of %s: %s", slug, exc.message)
        except Exception as exc:
            log.warning("Scheduled sync of %s failed (%s).", slug, type(exc).__name__)
