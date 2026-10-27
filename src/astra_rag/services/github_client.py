"""Talks to the GitHub REST API: URL parsing, listing folders, reading files."""
import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from ..config import HTTP_TIMEOUT_SECONDS, TOOL_MAX_FILE_BYTES
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
    return list_dir(repo, "", token)


def list_dir(repo: RepoRef, path: str, token: str) -> list[dict]:
    """Return the entries of a folder: [{'name': ..., 'type': 'file'|'dir'}, ...]."""
    missing = f"Folder '{path}' was not found in the repository." if path else None
    data = _get_json(repo, path, token, missing_message=missing)
    if not isinstance(data, list):
        raise AppError(f"'{path or '/'}' could not be read as a folder.", 502)
    return [{"name": e["name"], "type": e["type"]} for e in data]


def get_file(repo: RepoRef, path: str, token: str) -> dict:
    """Return {'path', 'sha', 'content'} for a text file, read from GitHub at call time."""
    data = _get_json(repo, path, token, missing_message=f"File '{path}' was not found in the repository.")
    if not isinstance(data, dict) or data.get("type") != "file":
        raise AppError(f"'{path}' is not a file.", 422)
    if data.get("size", 0) > TOOL_MAX_FILE_BYTES:
        raise AppError(f"File '{path}' is too large (limit {TOOL_MAX_FILE_BYTES // 1024} KB).", 422)
    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
    except (KeyError, ValueError):  # missing body, bad base64 or invalid UTF-8
        raise AppError(f"File '{path}' could not be read as UTF-8 text.", 422) from None
    return {"path": path, "sha": data.get("sha", ""), "content": content}


def _get_json(repo: RepoRef, path: str, token: str, missing_message: str | None):
    """GET a contents-API path and parse the JSON, translating failures to AppError."""
    quoted = quote(path.strip("/"), safe="/")
    request = urllib.request.Request(
        f"{repo.api_base}/repos/{repo.owner}/{repo.name}/contents/{quoted}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "astra-rag",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise _translate_http_error(exc, missing_message) from None
    except (urllib.error.URLError, TimeoutError):
        raise AppError("Could not reach GitHub. Check the URL and your network.", 502) from None


def _translate_http_error(exc: urllib.error.HTTPError, missing_message: str | None = None) -> AppError:
    if exc.code == 401:
        return AppError("GitHub rejected the token (401). Check that the PAT is valid and not expired.", 401)
    if exc.code in (403, 429):
        return AppError("GitHub denied the request (rate limit or missing permission on the token).", 403)
    if exc.code == 404:
        return AppError(missing_message or "Repository not found, or the token has no access to it.", 404)
    if exc.code == 409:
        return AppError("The repository is empty.", 409)
    return AppError(f"GitHub returned an unexpected error ({exc.code}).", 502)
