"""Talks to the GitHub REST API: listing the repo root."""
import json
import urllib.error
import urllib.request

from ..config import HTTP_TIMEOUT_SECONDS
from .errors import AppError
from .repo_ref import RepoRef


def list_root(repo: RepoRef, token: str) -> list[dict]:
    """Return the entries at the repo root: [{'name': ..., 'type': 'file'|'dir'}, ...]."""
    request = urllib.request.Request(
        f"{repo.api_base}/repos/{repo.full_name}/contents/",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "astra-rag",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise _translate_http_error(exc) from None
    except (urllib.error.URLError, TimeoutError):
        raise AppError("Could not reach GitHub. Check the URL and your network.", 502) from None

    if not isinstance(data, list):
        raise AppError("The repository root could not be read as a folder.", 502)
    return [{"name": e["name"], "type": e["type"]} for e in data]


def _translate_http_error(exc: urllib.error.HTTPError) -> AppError:
    if exc.code == 401:
        return AppError("GitHub rejected the token (401). Check that the PAT is valid and not expired.", 401)
    if exc.code in (403, 429):
        return AppError("GitHub denied the request (rate limit or missing permission on the token).", 403)
    if exc.code == 404:
        return AppError("Repository not found, or the token has no access to it.", 404)
    if exc.code == 409:
        return AppError("The repository is empty.", 409)
    return AppError(f"GitHub returned an unexpected error ({exc.code}).", 502)
