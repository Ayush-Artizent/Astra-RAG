"""Host-aware repository identity: which host, which repo, and a slug unique across hosts."""
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from ..config import SUPPORTED_HOST_KINDS
from .errors import AppError

_HOST_LABELS = {"azure_devops": "Azure DevOps", "gitlab": "GitLab", "bitbucket": "Bitbucket"}


@dataclass(frozen=True)
class RepoRef:
    host_kind: str               # github | ghe | azure_devops | gitlab | bitbucket
    host: str                    # lower-case hostname, e.g. github.com
    path_parts: tuple[str, ...]  # everything before the repo name (GitHub: the owner)
    name: str

    @property
    def owner(self) -> str:
        return "/".join(self.path_parts)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def slug(self) -> str:
        """Stable key for storage, e.g. github.com__acme__golden (hosts treat names case-insensitively)."""
        return "__".join((self.host, *self.path_parts, self.name)).lower()

    @property
    def clone_url(self) -> str:
        return f"https://{self.host}/{self.full_name}.git"

    @property
    def api_base(self) -> str:
        if self.host_kind == "github":
            return "https://api.github.com"
        return f"https://{self.host}/api/v3"  # GitHub Enterprise Server


def host_kind(host: str) -> str:
    if host == "github.com":
        return "github"
    if host == "dev.azure.com" or host.endswith(".visualstudio.com"):
        return "azure_devops"
    if host == "gitlab.com" or host.startswith("gitlab."):
        return "gitlab"
    if host == "bitbucket.org":
        return "bitbucket"
    return "ghe"  # any other host is treated as GitHub Enterprise Server


def parse_repo_url(url: str) -> RepoRef:
    """Accept https://github.com/owner/repo(.git)(/...) and return a RepoRef."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise AppError("Enter a valid repository URL, e.g. https://github.com/owner/repo")
    host = parsed.hostname.lower()
    kind = host_kind(host)
    if kind not in SUPPORTED_HOST_KINDS:
        raise AppError(f"{_HOST_LABELS[kind]} repositories are not supported yet. Use a GitHub URL for now.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise AppError("Enter a valid repository URL, e.g. https://github.com/owner/repo")
    name = re.sub(r"\.git$", "", parts[1])
    if not re.fullmatch(r"[\w.-]+", parts[0]) or not re.fullmatch(r"[\w.-]+", name):
        raise AppError("The repository URL contains invalid characters.")
    return RepoRef(host_kind=kind, host=host, path_parts=(parts[0],), name=name)
