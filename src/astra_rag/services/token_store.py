"""Remembers which PAT belongs to which repo URL in a git-ignored .env file.

Entries look like:
    ASTRA_REPO_ACME__GOLDEN_URL=https://github.com/acme/golden
    ASTRA_REPO_ACME__GOLDEN_TOKEN=ghp_...
The file is re-read on every call, so hand edits take effect without a restart.
Tokens are never returned by any API and never logged.
"""
import os
import re
import tempfile
import threading
from pathlib import Path

from ..config import ENV_FILE
from .github_client import RepoRef

_lock = threading.Lock()


def _key(repo: RepoRef) -> str:
    return "ASTRA_REPO_" + re.sub(r"[^A-Za-z0-9]", "_", f"{repo.owner}__{repo.name}").upper()


def _read(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                values[name.strip()] = value.strip().strip("'\"")
    return values


def _write(path: Path, values: dict[str, str]) -> None:
    """Write atomically so a crash can never leave a half-written secrets file."""
    body = "# Written by Astra-RAG. Contains secrets: never commit this file.\n"
    body += "".join(f"{k}={v}\n" for k, v in values.items())
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    try:
        path.chmod(0o600)  # owner-only where the OS supports it
    except OSError:
        pass


def save(repo: RepoRef, url: str, token: str, path: Path | None = None) -> None:
    """Remember `token` as the credential for this repo URL (replaces any earlier one)."""
    path = path or ENV_FILE
    key = _key(repo)
    with _lock:
        values = _read(path)
        values[f"{key}_URL"] = url.strip()
        values[f"{key}_TOKEN"] = token
        _write(path, values)


def get_token(repo: RepoRef, path: Path | None = None) -> str | None:
    """Return the saved token for this repo, or None."""
    values = _read(path or ENV_FILE)
    return values.get(f"{_key(repo)}_TOKEN") or None


def forget(repo: RepoRef, path: Path | None = None) -> bool:
    path = path or ENV_FILE
    key = _key(repo)
    with _lock:
        values = _read(path)
        removed = any([values.pop(f"{key}_{suffix}", None) is not None for suffix in ("URL", "TOKEN")])
        if removed:
            _write(path, values)
        return removed
