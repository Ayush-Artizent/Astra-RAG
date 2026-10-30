"""The local models (embeddings, reranker): downloaded and loaded in the background at startup, before anything uses them."""
import logging
import threading

from ..config import DENSE_MODEL, MODELS_PREFETCH, MODELS_WAIT_SECONDS, RERANK_MODEL, SPARSE_MODEL
from .errors import AppError

log = logging.getLogger(__name__)

COMPONENTS = {"embedder": [DENSE_MODEL, SPARSE_MODEL], "reranker": [RERANK_MODEL]}  # loaded in this order


class ModelsNotReady(AppError):
    """A model is still downloading or could not be downloaded; safe to show."""

    def __init__(self, message: str):
        super().__init__(message, 503)


_cond = threading.Condition()
_state = {name: {"state": "pending", "error": ""} for name in COMPONENTS}  # pending | downloading | ready | failed
_running = False


def _load(name: str) -> None:
    """Download (if missing), load and run each model once, so the first real call is neither slow nor able to fail here."""
    if name == "embedder":
        from .ingestion import embedder

        loaded = embedder._load_embedder()
        loaded.embed_passages(["warm up"])
        loaded.embed_query("warm up")
    else:
        from .context import rerank

        rerank._load_reranker().score("warm up", ["warm up", "warm up"])


def _set(name: str, state: str, error: str = "") -> None:
    with _cond:
        _state[name] = {"state": state, "error": error}
        _cond.notify_all()


def _run() -> None:
    global _running
    try:
        for name in COMPONENTS:
            _set(name, "downloading")
            try:
                _load(name)
            except Exception as exc:  # type name only: a host reply could carry more than we want to show
                log.warning("Model %s could not be prepared (%s).", name, type(exc).__name__)
                _set(name, "failed", type(exc).__name__)
            else:
                _set(name, "ready")
    finally:
        with _cond:
            _running = False
            _cond.notify_all()


def start_prefetch() -> None:
    """Start preparing every model that is not ready (a failed one is tried again). No-op when one run is going."""
    global _running
    if not MODELS_PREFETCH:
        return
    with _cond:
        if _running or all(s["state"] == "ready" for s in _state.values()):
            return
        for name, s in _state.items():
            if s["state"] != "ready":
                _state[name] = {"state": "pending", "error": ""}
        _running = True
    threading.Thread(target=_run, name="models-prefetch", daemon=True).start()


def _raise_unless_ready(names) -> None:
    for name in names:
        s = _state[name]
        if s["state"] == "ready":
            continue
        if s["state"] == "failed":
            raise ModelsNotReady(f"The {name} model could not be downloaded ({s['error']}). "
                                 "Check the network, then try again.")
        raise ModelsNotReady("The language models are still being downloaded. Try again in a few minutes.")


def require_ready(name: str) -> None:
    """Fail fast (503) instead of letting a request download a model. Off with ASTRA_MODELS_PREFETCH=0."""
    if not MODELS_PREFETCH:
        return
    with _cond:
        _raise_unless_ready((name,))


def wait_ready(names=("embedder",), timeout: float | None = None) -> None:
    """Block (background worker only) until the named models are ready; raises ModelsNotReady if they cannot be."""
    if not MODELS_PREFETCH:
        return
    start_prefetch()
    with _cond:
        _cond.wait_for(lambda: not _running or all(_state[n]["state"] == "ready" for n in names),
                       timeout or MODELS_WAIT_SECONDS)
        _raise_unless_ready(names)


def status() -> dict:
    with _cond:
        components = [{"name": n, "models": models, **_state[n]} for n, models in COMPONENTS.items()]
    return {"prefetch": MODELS_PREFETCH, "ready": all(c["state"] == "ready" for c in components),
            "components": components}
