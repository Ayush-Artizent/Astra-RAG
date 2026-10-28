"""Connect a golden repo (token, branch, structure, register, queue a sync) and change its tracked branch."""
from dataclasses import dataclass

from . import sync, token_store, validator
from .errors import AppError
from .ingestion.models import RepoContext
from .registry import repos, runs
from .registry.rules import check_branch_name
from .sources import PatCredential, adapter_for, parse_repo_url


class MissingItemsError(AppError):
    def __init__(self, missing: list[str], token_saved: bool):
        super().__init__("Repository is missing required items: " + ", ".join(missing), 422)
        self.missing, self.token_saved = missing, token_saved


@dataclass(frozen=True)
class Connected:
    run_id: int | None  # None: a sync was already running, so this one is queued as its follow-up
    context: RepoContext  # commit_sha is the branch head seen while connecting
    token_saved: bool


def connect(url: str, typed_token: str, branch: str = "") -> Connected:
    """Check token, branch and structure, then register the repo and queue a full sync; the caller starts it.

    Branch: the one asked for, else the repo's saved tracked branch, else the host's default branch.
    """
    repo = parse_repo_url(url)
    typed = typed_token.strip()
    token = typed or token_store.get_token(repo)
    if not token:
        raise AppError("A personal access token is required (none is saved for this repository).")
    requested = check_branch_name(branch) if branch.strip() else ""

    adapter = adapter_for(repo, PatCredential(token))
    branch = requested or repos.tracked_branch(repo.slug) or adapter.default_branch()
    head = adapter.head_sha(branch)  # a clear 404 if the branch does not exist
    entries = adapter.list_dir("", ref=branch)
    if typed:  # the host accepted the token, so remember it even if the repo turns out not to qualify
        token_store.save(repo, adapter.web_url, typed)
    missing = validator.find_missing(entries)
    if missing:
        raise MissingItemsError(missing, bool(typed))

    run_id = runs.register_and_queue(repo, adapter.web_url, branch, token_store.credential_ref(repo))
    return Connected(run_id, RepoContext(repo, branch, head), bool(typed))


def change_branch(slug: str, branch: str) -> dict:
    """Set a new tracked branch after checking it exists, then start a full rebuild from it."""
    branch = check_branch_name(branch)
    current = repos.get_repo(slug)
    if current is None:
        raise AppError("This repository is not registered. Connect it first.", 404)
    if current["tracked_branch"] != branch:
        ref = parse_repo_url(current["url"])
        token = token_store.get_token(ref)
        if not token:
            raise AppError("No token is saved for this repository. Reconnect it with a PAT first.")
        adapter_for(ref, PatCredential(token)).head_sha(branch)
        repos.set_tracked_branch(slug, branch)
        sync.request_sync(slug, "settings", force=True)
    return repos.get_repo(slug)
