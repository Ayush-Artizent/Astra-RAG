"""Registered repos (tracked branch vs indexed build) and project -> repo bindings."""
import sqlite3

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
    projects = [r["project_id"] for r in db.execute(
        "SELECT project_id FROM project_bindings WHERE repo_slug = ? ORDER BY project_id", (slug,))]
    return {
        "slug": slug, "url": row["url"], "host_kind": row["host_kind"], "host": row["host"],
        "tracked_branch": row["tracked_branch"], "index_state": state,
        "needs_rebuild": state in ("none", "incomplete") or row["indexed_config_version"] != row["config_version"],
        "indexed": indexed, "last_run": run_view(latest) if latest else None, "projects": projects,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _index_state(db, row, latest) -> str:
    """rebuilding | none | incomplete (a later run dropped the index, then failed) | ready."""
    if latest is not None and latest["state"] in ACTIVE_STATES:
        return "rebuilding"
    if row["indexed_run_id"] is None:
        return "none"
    # Until P5's alias swap, a rebuild drops the live collection first; if it then fails, search is partial.
    broken = db.execute("SELECT 1 FROM ingestion_runs WHERE repo_slug = ? AND id > ? AND index_replaced = 1"
                        " AND state != 'done' LIMIT 1", (row["slug"], row["indexed_run_id"])).fetchone()
    return "incomplete" if broken else "ready"
