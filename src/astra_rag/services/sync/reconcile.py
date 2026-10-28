"""Recovery: bring the registry back in step with what each repo's Qdrant alias actually serves.

The alias switch (Qdrant) and recording the run as done (SQLite) can't share a transaction. If the process
dies between them, the alias serves run N while the registry still names an older build and the startup
sweep has marked N failed. A swap only happens after the point count check passed, so N is complete and is
adopted. Anything else that doesn't add up keeps the alias serving and asks for a forced rebuild.
"""
import logging

from ..errors import AppError
from ..ingestion.store import QdrantStore, collection_name, version_run_id
from ..registry import repos, runs

log = logging.getLogger(__name__)


def run(store: QdrantStore | None = None) -> None:
    """Never raises: recovery must not stop the app from starting."""
    try:
        store = store or QdrantStore()
        store.ping()
    except AppError:
        log.warning("Qdrant is unreachable: index recovery skipped (it runs again before the nightly sync).")
        return
    for row in repos.recovery_rows():
        if row["active"]:
            continue  # a run in progress owns this repo's index
        try:
            _repair(store, row)
        except Exception as exc:
            log.warning("Index recovery for %s failed (%s).", row["slug"], type(exc).__name__)


def _repair(store: QdrantStore, row: dict) -> None:
    slug, indexed = row["slug"], row["indexed_run_id"]
    alias = collection_name(slug)
    collections = store.collections()
    target = store.alias_target(alias)
    if target not in collections:
        target = None  # no alias, or one left pointing at a deleted collection
    target_run = version_run_id(slug, target)
    if target is None:
        # A pre-P5 real collection under the alias name still serves; the first sync converts it.
        if indexed is not None and alias not in collections:
            log.warning("No index serves %s: rebuild requested.", slug)
            repos.request_rebuild(slug)
    elif target_run is not None and (indexed is None or target_run > indexed):
        run = runs.get_run(target_run)
        if run and run["repo_slug"] == slug and run["commit_sha"] and run["collection"] == target:
            runs.adopt_run(target_run)
            log.warning("Recovered %s: the index swap to run %s had completed.", slug, target_run)
        else:
            repos.request_rebuild(slug)
    elif target_run != indexed:
        repos.request_rebuild(slug)  # the alias serves something the registry did not build last
    store.drop_versions(slug, keep=target)
