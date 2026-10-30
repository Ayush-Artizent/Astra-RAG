"""GitHub (github.com and GitHub Enterprise Server) behind the SourceAdapter port."""
import base64
import re
from pathlib import Path
from urllib.parse import ParseResult, quote, urlencode

from ..errors import AppError
from ..repo_ref import RepoRef
from .base import CloneResult, DirEntry, SourceAdapter
from .git import git_clone
from .http import get_bytes, get_json

_LABEL = "GitHub"
_URL_HINT = "Enter a valid repository URL, e.g. https://github.com/owner/repo"
_PATH_NOT_FOUND = "That path was not found in the repository."


class GitHubAdapter(SourceAdapter):
    @classmethod
    def parse_url(cls, parts: ParseResult, kind: str) -> RepoRef:
        """Accept https://<host>/owner/repo(.git)(/...)."""
        segments = [p for p in parts.path.split("/") if p]
        if len(segments) < 2:
            raise AppError(_URL_HINT)
        name = re.sub(r"\.git$", "", segments[1])
        if not re.fullmatch(r"[\w.-]+", segments[0]) or not re.fullmatch(r"[\w.-]+", name):
            raise AppError("The repository URL contains invalid characters.")
        return RepoRef(host_kind=kind, host=parts.hostname.lower(), path_parts=(segments[0],), name=name)

    @property
    def web_url(self) -> str:
        return f"https://{self.ref.host}/{self.ref.full_name}"

    @property
    def clone_url(self) -> str:
        return f"https://{self.ref.host}/{self.ref.full_name}.git"

    @property
    def api_base(self) -> str:
        if self.ref.host_kind == "github":
            return "https://api.github.com"
        return f"https://{self.ref.host}/api/v3"  # GitHub Enterprise Server

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret()}", "Accept": accept, "User-Agent": "astra-rag"}

    def _repo_url(self, suffix: str = "") -> str:
        return f"{self.api_base}/repos/{self.ref.full_name}{suffix}"

    @staticmethod
    def _at(ref: str | None) -> str:
        return f"?{urlencode({'ref': ref})}" if ref else ""

    def list_dir(self, path: str = "", ref: str | None = None) -> list[DirEntry]:
        clean = path.strip("/")
        # Root keeps its trailing slash ("contents/"), exactly as the original listing call did.
        data = get_json(self._repo_url(f"/contents/{quote(clean)}{self._at(ref)}"), self._headers(), _LABEL,
                        not_found=_PATH_NOT_FOUND if clean else None)
        if not isinstance(data, list):
            raise AppError("That path could not be read as a folder." if clean
                           else "The repository root could not be read as a folder.", 502)
        return [{"name": e["name"], "type": e["type"]} for e in data]

    def read_file(self, path: str, ref: str | None = None) -> bytes:
        url = self._repo_url(f"/contents/{quote(path.strip('/'))}{self._at(ref)}")
        return get_bytes(url, self._headers("application/vnd.github.raw+json"), _LABEL, not_found=_PATH_NOT_FOUND)

    def head_sha(self, branch: str) -> str:
        data = get_json(self._repo_url(f"/git/ref/heads/{quote(branch, safe='/')}"), self._headers(), _LABEL,
                        not_found="Branch not found in the repository.")
        return _field(data, "object", "sha")

    def default_branch(self) -> str:
        return _field(get_json(self._repo_url(), self._headers(), _LABEL), "default_branch")

    def is_ancestor(self, base: str, head: str) -> bool:
        data = get_json(self._repo_url(f"/compare/{quote(base)}...{quote(head)}"), self._headers(), _LABEL,
                        not_found="Commit not found in the repository.")
        # "ahead" or "identical" means `head` contains `base`; "behind"/"diverged" means it does not.
        return _field(data, "status") in ("ahead", "identical")

    def clone(self, dest: Path, branch: str | None = None) -> CloneResult:
        basic = base64.b64encode(f"x-access-token:{self._secret()}".encode()).decode()
        return git_clone(self.clone_url, dest, branch, f"Authorization: Basic {basic}")

    def citation_url(self, path: str, ref: str, lines: tuple[int, int] | None = None) -> str:
        url = f"https://{self.ref.host}/{self.ref.full_name}/blob/{quote(ref)}/{quote(path)}"
        return f"{url}#L{lines[0]}-L{lines[1]}" if lines else url


def _field(data, *keys):
    """Pull a nested value out of a JSON reply, or fail with a safe 502 if the shape is wrong."""
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            raise AppError(f"{_LABEL} returned a response that could not be read.", 502)
        data = data[key]
    return data
