"""Azure DevOps Services (dev.azure.com and legacy *.visualstudio.com) behind the SourceAdapter port."""
import base64
import re
from pathlib import Path
from urllib.parse import ParseResult, quote, unquote, urlencode

from ..errors import AppError
from ..repo_ref import RepoRef
from .base import CloneResult, DirEntry, SourceAdapter
from .git import git_clone
from .http import get_bytes
from .json_reply import parse_json

_LABEL = "Azure DevOps"
_URL_HINT = "Enter a valid repository URL, e.g. https://dev.azure.com/org/project/_git/repo"
_PATH_NOT_FOUND = "That path was not found in the repository."
_API_VERSION = "7.1"
_CANONICAL_HOST = "dev.azure.com"
_BAD_NAME = re.compile(r'[\x00-\x1f\\/:*?"<>|]')
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_OBJECT_TYPES = {"tree": "dir", "blob": "file", "commit": "submodule"}


class AzureDevOpsAdapter(SourceAdapter):
    @classmethod
    def parse_url(cls, parts: ParseResult, kind: str) -> RepoRef:
        """Accept .../{org}/{project}/_git/{repo}, the {org}.visualstudio.com form and the project-less shorthand."""
        host = parts.hostname.lower()
        segments = [unquote(p).strip() for p in parts.path.split("/") if p]
        scope: list[str] = []
        if host != _CANONICAL_HOST:  # legacy: the organisation is the subdomain
            scope.append(host.split(".")[0])
            if segments and segments[0].lower() == "defaultcollection":
                segments = segments[1:]
        if "_git" not in segments or segments.index("_git") + 1 >= len(segments):
            raise AppError(_URL_HINT)
        index = segments.index("_git")
        scope += segments[:index]
        repo = segments[index + 1]
        if not 1 <= len(scope) <= 2:
            raise AppError(_URL_HINT)
        if len(scope) == 1:  # shorthand: the project has the same name as the repo
            scope.append(repo)
        if any(_BAD_NAME.search(p) or p in ("", ".", "..") for p in (*scope, repo)):
            raise AppError("The repository URL contains invalid characters.")
        # Both hosts name the same repo, so they share one slug (token, clone folder, collection).
        return RepoRef(host_kind=kind, host=_CANONICAL_HOST, path_parts=tuple(scope), name=repo)

    @property
    def _web_url(self) -> str:
        org, project = self.ref.path_parts
        return f"https://{self.ref.host}/{quote(org)}/{quote(project)}/_git/{quote(self.ref.name)}"

    @property
    def clone_url(self) -> str:
        return self._web_url

    def _repo_url(self, suffix: str = "") -> str:
        org, project = self.ref.path_parts
        return (f"https://{self.ref.host}/{quote(org)}/{quote(project)}"
                f"/_apis/git/repositories/{quote(self.ref.name)}{suffix}")

    def _basic_header(self) -> str:
        return "Basic " + base64.b64encode(f":{self._secret()}".encode()).decode()

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        return {"Authorization": self._basic_header(), "Accept": accept, "User-Agent": "astra-rag"}

    @staticmethod
    def _query(params: list[tuple[str, str]], ref: str | None = None) -> str:
        if ref:
            kind = "commit" if _COMMIT_SHA.fullmatch(ref) else "branch"
            params = [*params, ("versionDescriptor.version", ref), ("versionDescriptor.versionType", kind)]
        # "/" stays readable in paths; spaces become %20 rather than "+".
        return urlencode([*params, ("api-version", _API_VERSION)], quote_via=lambda s, *_: quote(s, safe="/"))

    def _json(self, url: str, not_found: str | None = None):
        # An invalid or expired PAT often gets a 203 with an HTML sign-in page instead of a 401.
        return parse_json(get_bytes(url, self._headers(), _LABEL, not_found), _LABEL, unauthorized=_rejected_token)

    def list_dir(self, path: str = "", ref: str | None = None) -> list[DirEntry]:
        clean = path.strip("/")
        query = self._query([("scopePath", "/" + clean), ("recursionLevel", "OneLevel")], ref)
        data = self._json(self._repo_url(f"/items?{query}"), not_found=_PATH_NOT_FOUND if clean else None)
        items = _field(data, "value")
        if not isinstance(items, list):
            raise AppError(f"{_LABEL} returned a response that could not be read.", 502)
        entries: list[DirEntry] = []
        for item in items:
            item_path = str(item.get("path", "")).strip("/") if isinstance(item, dict) else ""
            if not item_path or item_path == clean:  # the first result is the folder itself
                continue
            kind = _OBJECT_TYPES.get(item.get("gitObjectType"), "dir" if item.get("isFolder") else "file")
            entries.append({"name": item_path.rsplit("/", 1)[-1], "type": kind})
        return entries

    def read_file(self, path: str, ref: str | None = None) -> bytes:
        query = self._query([("path", "/" + path.strip("/")), ("$format", "octetStream"), ("download", "true")], ref)
        return get_bytes(self._repo_url(f"/items?{query}"), self._headers("application/octet-stream"), _LABEL,
                         not_found=_PATH_NOT_FOUND)

    def head_sha(self, branch: str) -> str:
        query = self._query([("filter", f"heads/{branch}")])
        data = self._json(self._repo_url(f"/refs?{query}"))
        for item in _field(data, "value"):  # the filter is a prefix match, so look for the exact branch
            if isinstance(item, dict) and item.get("name") == f"refs/heads/{branch}":
                return _field(item, "objectId")
        raise AppError("Branch not found in the repository.", 404)

    def default_branch(self) -> str:
        data = self._json(self._repo_url(f"?api-version={_API_VERSION}"))
        if not isinstance(data, dict):
            raise AppError(f"{_LABEL} returned a response that could not be read.", 502)
        name = data.get("defaultBranch")
        if not name:
            raise AppError("The repository is empty.", 409)
        return name.removeprefix("refs/heads/")

    def is_ancestor(self, base: str, head: str) -> bool:
        query = (f"baseVersion={quote(base)}&baseVersionType=commit&targetVersion={quote(head)}"
                 f"&targetVersionType=commit&api-version={_API_VERSION}")
        data = self._json(self._repo_url(f"/diffs/commits?{query}"), not_found="Commit not found in the repository.")
        # behindCount = commits in `base` that `head` lacks; zero means `head` contains `base`.
        return _field(data, "behindCount") == 0

    def clone(self, dest: Path, branch: str | None = None) -> CloneResult:
        return git_clone(self.clone_url, dest, branch, f"Authorization: {self._basic_header()}")

    def citation_url(self, path: str, ref: str, lines: tuple[int, int] | None = None) -> str:
        version = ("GC" if _COMMIT_SHA.fullmatch(ref) else "GB") + ref
        url = f"{self._web_url}?path=/{quote(path.strip('/'))}&version={quote(version)}"
        if lines:  # ADO's end position is exclusive: column 1 of the line after the range
            url += f"&line={lines[0]}&lineEnd={lines[1] + 1}&lineStartColumn=1&lineEndColumn=1"
        return url


def _rejected_token() -> AppError:
    return AppError(f"{_LABEL} rejected the token (401). Check that the PAT is valid and not expired.", 401)


def _field(data, *keys):
    """Pull a nested value out of a JSON reply, or fail with a safe 502 if the shape is wrong."""
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            raise AppError(f"{_LABEL} returned a response that could not be read.", 502)
        data = data[key]
    return data
