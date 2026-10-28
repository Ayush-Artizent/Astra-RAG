"""Ingestion runs: queue (coalescing while one is active), progress, finish, recovery and the restart sweep."""
import json

from ..errors import AppError
from ..repo_ref import RepoRef
from .db import now, transaction

ACTIVE_STATES = ("queued", "running")
RECOVERED_NOTE = "Recovered at startup: the index swap had completed."
_JSON_FIELDS = ("files_skipped", "warnings")
_UPDATABLE = {"state", "commit_sha", "collection", "index_replaced", "files_loaded", "files_skipped", "chunks_total",
              "chunks_stored", "warnings", "error", "started_at", "finished_at"}


def register_and_queue(ref: RepoRef, url: str, branch: str, credential_ref: str, triggered_by: str = "connect",
                       force: bool = True) -> int | None:
    """Connect: register or update the repo and queue a run, atomically.

    Only a real change of tracked branch bumps config_version. The host just accepted the token, so the
    last source error is cleared. Returns None when a run is already active (the request is coalesced).
    """
    stamp = now()
    with transaction() as db:
        row = db.execute("SELECT 1 FROM repos WHERE slug = ?", (ref.slug,)).fetchone()
        if row is None:
            db.execute("INSERT INTO repos (slug, url, host_kind, host, tracked_branch, credential_ref, created_at,"
                       " updated_at, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (ref.slug, url, ref.host_kind, ref.host, branch, credential_ref, stamp, stamp, stamp))
        else:
            db.execute("UPDATE repos SET url = ?, credential_ref = ?, updated_at = ?, last_checked_at = ?,"
                       " source_error = '', config_version = config_version + (tracked_branch != ?),"
                       " tracked_branch = ? WHERE slug = ?",
                       (url, credential_ref, stamp, stamp, branch, branch, ref.slug))
        return _queue(db, ref.slug, triggered_by, force, stamp)


def queue_run(slug: str, triggered_by: str, force: bool = False) -> int | None:
    """Queue a run for a registered repo, or coalesce into a follow-up if one is active (returns None).

    Never touches config_version or tracked_branch: a sync is not a configuration change.
    """
    with transaction() as db:
        return _queue(db, slug, triggered_by, force, now())


def _queue(db, slug: str, triggered_by: str, force: bool, stamp: str) -> int | None:
    if db.execute("SELECT 1 FROM ingestion_runs WHERE repo_slug = ? AND state IN (?, ?)",
                  (slug, *ACTIVE_STATES)).fetchone():
        db.execute("UPDATE repos SET sync_pending = 1, sync_force = MAX(sync_force, ?) WHERE slug = ?",
                   (int(force), slug))
        return None
    cursor = db.execute(
        "INSERT INTO ingestion_runs (repo_slug, state, branch, config_version, triggered_by, queued_at)"
        " SELECT slug, 'queued', tracked_branch, config_version, ?, ? FROM repos WHERE slug = ?",
        (triggered_by, stamp, slug))
    if not cursor.rowcount:
        raise AppError("This repository is not registered. Connect it first.", 404)
    # This run rebuilds from scratch, so it also satisfies any follow-up that was waiting.
    db.execute("UPDATE repos SET sync_pending = 0, sync_force = 0 WHERE slug = ?", (slug,))
    return cursor.lastrowid


def take_pending(slug: str) -> tuple[bool, bool]:
    """Read and clear the coalesced follow-up request: (pending, force)."""
    with transaction() as db:
        row = db.execute("SELECT sync_pending, sync_force FROM repos WHERE slug = ?", (slug,)).fetchone()
        if row is None or not row["sync_pending"]:
            return False, False
        db.execute("UPDATE repos SET sync_pending = 0, sync_force = 0 WHERE slug = ?", (slug,))
        return True, bool(row["sync_force"])


def update_run(run_id: int, **fields) -> None:
    """Record progress on a run that is still active (a finished or swept run is left alone)."""
    if not fields:
        return
    columns, values = _assignments(fields)
    with transaction() as db:
        db.execute(f"UPDATE ingestion_runs SET {columns} WHERE id = ? AND state IN (?, ?)",
                   (*values, run_id, *ACTIVE_STATES))


def finish_run(run_id: int, state: str, **fields) -> None:
    """Close an active run. A `done` run becomes the repo's indexed build unless a newer run already is.

    A failed run never touches the repo's indexed_* fields, so they keep describing the last good build.
    """
    if state not in ("done", "failed"):
        raise ValueError(f"Not a final state: {state}")
    columns, values = _assignments({**fields, "state": state, "finished_at": now()})
    with transaction() as db:
        cursor = db.execute(f"UPDATE ingestion_runs SET {columns} WHERE id = ? AND state IN (?, ?)",
                            (*values, run_id, *ACTIVE_STATES))
        if cursor.rowcount and state == "done":
            _promote(db, run_id)


def adopt_run(run_id: int) -> None:
    """Recovery: the alias already serves this finished run's index, so record it as done and indexed."""
    with transaction() as db:
        cursor = db.execute("UPDATE ingestion_runs SET state = 'done', error = ?, finished_at = ?"
                            " WHERE id = ? AND state = 'failed'", (RECOVERED_NOTE, now(), run_id))
        if cursor.rowcount:
            _promote(db, run_id)


def _promote(db, run_id: int) -> None:
    db.execute(
        "UPDATE repos SET indexed_run_id = r.id, indexed_branch = r.branch, indexed_commit_sha = r.commit_sha,"
        " indexed_collection = r.collection, indexed_config_version = r.config_version,"
        " indexed_at = r.finished_at FROM ingestion_runs AS r"
        " WHERE r.id = ? AND repos.slug = r.repo_slug"
        " AND (repos.indexed_run_id IS NULL OR repos.indexed_run_id < r.id)", (run_id,))


def _assignments(fields: dict) -> tuple[str, list]:
    """`col = ?` list for a run UPDATE; only known columns, so names are never taken from input."""
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"Not run fields: {sorted(unknown)}")
    values = [json.dumps(v) if k in _JSON_FIELDS else v for k, v in fields.items()]
    return ", ".join(f"{k} = ?" for k in fields), values


def get_run(run_id: int) -> dict | None:
    """The raw run row (including repo_slug), for the sync worker and recovery."""
    with transaction(write=False) as db:
        row = db.execute("SELECT * FROM ingestion_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def latest_run(slug: str) -> dict | None:
    with transaction(write=False) as db:
        row = db.execute("SELECT * FROM ingestion_runs WHERE repo_slug = ? ORDER BY id DESC LIMIT 1",
                         (slug,)).fetchone()
    return run_view(row) if row else None


def sweep_interrupted() -> int:
    """At startup, nothing can still be running: fail what a previous process left queued or running."""
    with transaction() as db:
        return db.execute("UPDATE ingestion_runs SET state = 'failed', error = ?, finished_at = ?"
                          " WHERE state IN (?, ?)",
                          ("Interrupted by a server restart.", now(), *ACTIVE_STATES)).rowcount


def run_view(row) -> dict:
    view = {k: row[k] for k in row.keys() if k not in ("repo_slug", "config_version", "index_replaced")}
    view["run_id"] = view.pop("id")
    for key in _JSON_FIELDS:
        view[key] = json.loads(view[key])
    return view
