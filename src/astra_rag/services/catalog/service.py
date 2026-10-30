"""Looks up a project's repo and returns its catalog, read live from the host."""
from .. import token_store
from ..errors import AppError
from ..registry import repos
from ..registry.rules import check_project_id
from ..sources import PatCredential, adapter_for, parse_repo_url
from .catalog import CatalogCache
from .live import AdapterReader
from .models import Catalog

_cache = CatalogCache()


def catalog_for_repo(slug: str) -> tuple[dict, Catalog]:
    """Return (repo, catalog) for a registered repo, on its tracked branch."""
    repo = repos.get_repo(slug)
    if repo is None:
        raise AppError("This repository is not registered. Connect it first.", 404)
    ref = parse_repo_url(repo["url"])
    token = token_store.get_token(ref)
    if not token:
        raise AppError("No token is saved for this repository. Reconnect it with a PAT first.")
    branch = repo["tracked_branch"]
    reader = AdapterReader(adapter_for(ref, PatCredential(token)), branch)
    return repo, _cache.get(f"{slug}@{branch}", reader)


def catalog_for_project(project_id: str) -> tuple[dict, Catalog]:
    project = repos.get_project(check_project_id(project_id))
    if project is None:
        raise AppError("This project is not bound to a repository.", 404)
    return catalog_for_repo(project["repo"]["slug"])
