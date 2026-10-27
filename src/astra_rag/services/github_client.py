"""Talks to the GitHub REST API: URL parsing and listing the repo root."""
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from ..config import HTTP_TIMEOUT_SECONDS
from .errors import AppError


@dataclass(frozen=True)
class RepoRef:
    host: str
    owner: str
    name: str

    @property
    def clone_url(self) -> str:
        return f"https://{self.host}/{self.owner}/{self.name}.git"

    @property
    def api_base(self) -> str:
        if self.host == "github.com":
            return "https://api.github.com"
        return f"https://{self.host}/api/v3"  # GitHub Enterprise Server


def parse_repo_url(url: str) -> RepoRef:
    """Accept https://github.com/owner/repo(.git)(/...) and return a RepoRef."""
    parsed = urlparse((url or "").strip())
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.scheme != "https" or not parsed.hostname or len(parts) < 2:
        raise AppError("Enter a valid repository URL, e.g. https://github.com/owner/repo")
    name = re.sub(r"\.git$", "", parts[1])
    if not re.fullmatch(r"[\w.-]+", parts[0]) or not re.fullmatch(r"[\w.-]+", name):
        raise AppError("The repository URL contains invalid characters.")
    return RepoRef(host=parsed.hostname.lower(), owner=parts[0], name=name)


def list_root(repo: RepoRef, token: str) -> list[dict]:
    """Return the entries at the repo root: [{'name': ..., 'type': 'file'|'dir'}, ...]."""
    request = urllib.request.Request(
        f"{repo.api_base}/repos/{repo.owner}/{repo.name}/contents/",
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
