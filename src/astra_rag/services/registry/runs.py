"""Ingestion runs: queue (with the one-active-run guard), progress, finish, and the restart sweep."""
import json

from ..errors import AppError
from ..repo_ref import RepoRef
from .db import now, transaction

ACTIVE_STATES = ("queued", "running")
_JSON_FIELDS = ("files_skipped", "warnings")
_UPDATABLE = {"state", "commit_sha", "index_replaced", "files_loaded", "files_skipped", "chunks_total",
              "chunks_stored", "warnings", "error", "started_at", "finished_at"}


def queue_run(ref: RepoRef, url: str, branch: str, credential_ref: str, collection: str) -> int:
    """Register or update the repo and queue a run, atomically; 409 if a run is already active for it."""
    stamp = now()
    with transaction() as db:
        if db.execute("SELECT 1 FROM ingestion_runs WHERE repo_slug = ? AND state IN (?, ?)",
                      (ref.slug, *ACTIVE_STATES)).fetchone():
            raise AppError("An ingestion is already running for this repository. Try again when it finishes.", 409)
        row = db.execute("SELECT tracked_branch FROM repos WHERE slug = ?", (ref.slug,)).fetchone()
        if row is None:
            db.execute("INSERT INTO repos (slug, url, host_kind, host, tracked_branch, credential_ref, created_at,"
                       " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (ref.slug, url, ref.host_kind, ref.host, branch, credential_ref, stamp, stamp))
        else:
            # A new branch is a new configuration: bump the version so older runs can't satisfy it.
            db.execute("UPDATE repos SET url = ?, credential_ref = ?, updated_at = ?,"
                       " config_version = config_version + (tracked_branch != ?), tracked_branch = ?"
                       " WHERE slug = ?", (url, credential_ref, stamp, branch, branch, ref.slug))
        cursor = db.execute(
            "INSERT INTO ingestion_runs (repo_slug, state, branch, config_version, collection, queued_at)"
            " SELECT slug, 'queued', tracked_branch, config_version, ?, ? FROM repos WHERE slug = ?",
            (collection, stamp, ref.slug))
        return cursor.lastrowid


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
