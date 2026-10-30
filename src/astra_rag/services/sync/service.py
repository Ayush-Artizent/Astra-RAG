"""Keep a repo's index on the latest commit of its tracked branch: check, queue, clone, ingest, follow up."""
import logging
from pathlib import Path

from .. import cloner, token_store
from ..errors import AppError
from ..ingestion import pipeline
from ..ingestion.models import RepoContext
from ..registry import repos, runs
from ..sources import PatCredential, adapter_for, parse_repo_url
from . import worker

log = logging.getLogger(__name__)
NO_TOKEN = "No token is saved for this repository. Reconnect it with a PAT."
REJECTED = "The host rejected the saved token. Reconnect this repository with a new PAT."


def request_sync(slug: str, triggered_by: str, force: bool = False) -> dict:
    """Check the branch head and queue a rebuild if it moved (always, if forced or the config changed).

    Returns {state: up_to_date | queued | pending, ...}. While a run is active the request is coalesced into
    one follow-up run (`pending`). Host failures are recorded on the repo as `source_error` and re-raised.
    """
    repo = repos.get_repo(slug)
    if repo is None:
        raise AppError("This repository is not registered. Connect it first.", 404)
    if not force and repo["index_state"] != "rebuilding":
        head = _check_head(repo)
        indexed = repo["indexed"]
        if indexed and indexed["commit_sha"] == head and not repo["needs_rebuild"]:
            return {"state": "up_to_date", "commit_sha": head}
    run_id = runs.queue_run(slug, triggered_by, force)
    if run_id is None:
        return {"state": "pending"}
    start(run_id)
    return {"state": "queued", "run_id": run_id}


def start(run_id: int) -> None:
    worker.submit(execute, run_id)


def execute(run_id: int) -> None:
    """Clone and ingest one queued run, then start the follow-up that arrived meanwhile, if any."""
    run = runs.get_run(run_id)
    if run is None:
        return
    slug = run["repo_slug"]
    try:
        _build(run_id, slug, run["branch"])
    finally:
        _follow_up(slug)


def _build(run_id: int, slug: str, branch: str) -> None:
    try:
        adapter = _adapter(repos.get_repo(slug))
        clone = cloner.clone_repo(adapter, branch)
    except AppError as exc:
        repos.mark_checked(slug, _source_message(exc))
        runs.finish_run(run_id, "failed", error=exc.message)
        return
    except Exception as exc:
        log.warning("Clone for %s failed (%s).", slug, type(exc).__name__)
        runs.finish_run(run_id, "failed", error="Unexpected error while cloning.")
        return
    runs.update_run(run_id, commit_sha=clone.commit_sha)
    repos.mark_checked(slug)
    pipeline.run_ingestion(run_id, RepoContext(adapter.ref, branch, clone.commit_sha), Path(clone.path))


def _follow_up(slug: str) -> None:
    try:
        pending, force = runs.take_pending(slug)
        if pending:
            request_sync(slug, "follow_up", force)
    except AppError as exc:
        log.warning("Follow-up sync for %s: %s", slug, exc.message)
    except Exception as exc:
        log.warning("Follow-up sync for %s failed (%s).", slug, type(exc).__name__)


def _check_head(repo: dict) -> str:
    """The tracked branch's head commit; a failure is recorded on the repo before it is raised."""
    slug = repo["slug"]
    try:
        head = _adapter(repo).head_sha(repo["tracked_branch"])
    except AppError as exc:
        repos.mark_checked(slug, _source_message(exc))
        raise
    repos.mark_checked(slug)
    return head


def _adapter(repo: dict):
    ref = parse_repo_url(repo["url"])
    token = token_store.get_token(ref)
    if not token:
        raise AppError(NO_TOKEN, 400)
    return adapter_for(ref, PatCredential(token))


def _source_message(exc: AppError) -> str:
    return REJECTED if exc.status == 401 else exc.message
