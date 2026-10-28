"""Registered repos (tracked branch vs indexed build) and project -> repo bindings."""
import sqlite3
from datetime import datetime, timedelta, timezone

from ..errors import AppError
from .db import now, transaction
from .runs import ACTIVE_STATES, run_view


def tracked_branch(slug: str) -> str | None:
    with transaction(write=False) as db:
        row = db.execute("SELECT tracked_branch FROM repos WHERE slug = ?", (slug,)).fetchone()
    return row["tracked_branch"] if row else None


def get_repo(slug: str) -> dict | None:
    with transaction(write=False) as db:
        row = db.execute("SELECT * FROM repos WHERE slug = ?", (slug,)).fetchone()
        return _view(db, row) if row else None


def list_repos() -> list[dict]:
    with transaction(write=False) as db:
        return [_view(db, row) for row in db.execute("SELECT * FROM repos ORDER BY slug").fetchall()]


def set_tracked_branch(slug: str, branch: str) -> None:
    """Change the tracked branch; a real change bumps config_version, so the repo needs a rebuild."""
    with transaction() as db:
        cursor = db.execute("UPDATE repos SET tracked_branch = ?, config_version = config_version + 1,"
                            " updated_at = ? WHERE slug = ? AND tracked_branch != ?", (branch, now(), slug, branch))
        if not cursor.rowcount and not db.execute("SELECT 1 FROM repos WHERE slug = ?", (slug,)).fetchone():
            raise AppError("This repository is not registered. Connect it first.", 404)


def mark_checked(slug: str, error: str = "") -> None:
    """Record a check of the host: when, and the safe error message if it failed ('' clears it)."""
    with transaction() as db:
        db.execute("UPDATE repos SET last_checked_at = ?, source_error = ? WHERE slug = ?", (now(), error, slug))


def request_rebuild(slug: str) -> None:
    """Ask for a forced follow-up sync (recovery found the index and the registry out of step)."""
    with transaction() as db:
        db.execute("UPDATE repos SET sync_pending = 1, sync_force = 1 WHERE slug = ?", (slug,))


def all_slugs() -> list[str]:
    with transaction(write=False) as db:
        return [r["slug"] for r in db.execute("SELECT slug FROM repos ORDER BY slug")]


def due_slugs(older_than_hours: int) -> list[str]:
    """Repos never checked, or not checked for a while, or waiting for a follow-up (startup catch-up)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat(timespec="seconds")
    with transaction(write=False) as db:
        return [r["slug"] for r in db.execute(
            "SELECT slug FROM repos WHERE last_checked_at IS NULL OR last_checked_at < ? OR sync_pending = 1"
            " ORDER BY slug", (cutoff,))]


def recovery_rows() -> list[dict]:
    """What startup recovery compares with Qdrant: the indexed build and whether a run is active."""
    with transaction(write=False) as db:
        return [{**dict(r), "active": bool(db.execute(
            "SELECT 1 FROM ingestion_runs WHERE repo_slug = ? AND state IN (?, ?)",
            (r["slug"], *ACTIVE_STATES)).fetchone())}
            for r in db.execute("SELECT slug, indexed_run_id, config_version FROM repos ORDER BY slug")]


def bind_project(project_id: str, slug: str) -> dict:
    """Bind a project to one repo, replacing any earlier binding in the same statement."""
    try:
        with transaction() as db:
            db.execute("INSERT INTO project_bindings (project_id, repo_slug, bound_at) VALUES (?, ?, ?)"
                       " ON CONFLICT (project_id) DO UPDATE SET repo_slug = excluded.repo_slug,"
                       " bound_at = excluded.bound_at", (project_id, slug, now()))
    except sqlite3.IntegrityError:  # the foreign key: unknown repo. The old binding is untouched.
        raise AppError("This repository is not registered. Connect it first.", 404) from None
    return get_project(project_id)


def get_project(project_id: str) -> dict | None:
    with transaction(write=False) as db:
        row = db.execute("SELECT * FROM project_bindings WHERE project_id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        repo = db.execute("SELECT * FROM repos WHERE slug = ?", (row["repo_slug"],)).fetchone()
        return {"project_id": project_id, "bound_at": row["bound_at"], "repo": _view(db, repo)}


def _view(db, row) -> dict:
    """What the API shows for a repo. Never the token or where it is kept (credential_ref)."""
    slug = row["slug"]
    latest = db.execute("SELECT * FROM ingestion_runs WHERE repo_slug = ? ORDER BY id DESC LIMIT 1",
                        (slug,)).fetchone()
    indexed = None
    if row["indexed_run_id"] is not None:
        indexed = {"run_id": row["indexed_run_id"], "branch": row["indexed_branch"],
                   "commit_sha": row["indexed_commit_sha"], "collection": row["indexed_collection"],
                   "at": row["indexed_at"]}
    state = _index_state(db, row, latest)
    needs_rebuild = state in ("none", "incomplete") or row["indexed_config_version"] != row["config_version"]
    projects = [r["project_id"] for r in db.execute(
        "SELECT project_id FROM project_bindings WHERE repo_slug = ? ORDER BY project_id", (slug,))]
    return {
        "slug": slug, "url": row["url"], "host_kind": row["host_kind"], "host": row["host"],
        "tracked_branch": row["tracked_branch"], "index_state": state, "needs_rebuild": needs_rebuild,
        "sync_status": _sync_status(row, latest, needs_rebuild),
        "sync": {"last_checked_at": row["last_checked_at"], "pending": bool(row["sync_pending"]),
                 "source_error": row["source_error"]},
        "indexed": indexed, "last_run": run_view(latest) if latest else None, "projects": projects,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _sync_status(row, latest, needs_rebuild: bool) -> str:
    """syncing | queued | pending | source_error | never_indexed | out_of_date | up_to_date (as of the last check)."""
    if latest is not None and latest["state"] == "running":
        return "syncing"
    if latest is not None and latest["state"] == "queued":
        return "queued"
    if row["sync_pending"]:
        return "pending"
    if row["source_error"]:
        return "source_error"
    if row["indexed_run_id"] is None:
        return "never_indexed"
    return "out_of_date" if needs_rebuild else "up_to_date"


def _index_state(db, row, latest) -> str:
    """rebuilding | none | incomplete (a later run dropped the index, then failed) | ready."""
    if latest is not None and latest["state"] in ACTIVE_STATES:
        return "rebuilding"
    if row["indexed_run_id"] is None:
        return "none"
    # Only runs from before P5 set index_replaced (they dropped the live collection before rebuilding).
    broken = db.execute("SELECT 1 FROM ingestion_runs WHERE repo_slug = ? AND id > ? AND index_replaced = 1"
                        " AND state != 'done' LIMIT 1", (row["slug"], row["indexed_run_id"])).fetchone()
    return "incomplete" if broken else "ready"
