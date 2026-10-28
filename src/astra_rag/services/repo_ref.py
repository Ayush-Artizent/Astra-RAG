"""Host-aware repository identity: which host, which repo, and a slug unique across hosts."""
from dataclasses import dataclass


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
