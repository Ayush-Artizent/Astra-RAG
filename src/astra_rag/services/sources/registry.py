"""Picks the adapter for a repo URL. Adding a host means adding one entry to ADAPTERS."""
from urllib.parse import urlparse

from ...config import SUPPORTED_HOST_KINDS
from ..errors import AppError
from ..repo_ref import RepoRef, host_kind
from .base import SourceAdapter
from .credentials import Credential
from .azure_devops import AzureDevOpsAdapter
from .github import GitHubAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    "github": GitHubAdapter, "ghe": GitHubAdapter, "azure_devops": AzureDevOpsAdapter,
}

_HOST_LABELS = {"gitlab": "GitLab", "bitbucket": "Bitbucket"}


def parse_repo_url(url: str) -> RepoRef:
    """Check scheme and host here; the host's adapter owns the rest of the URL shape."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise AppError("Enter a valid repository URL, e.g. https://github.com/owner/repo")
    kind = host_kind(parsed.hostname.lower())
    if kind not in SUPPORTED_HOST_KINDS:
        raise AppError(f"{_HOST_LABELS[kind]} repositories are not supported yet. Use a GitHub or Azure DevOps URL for now.")
    return ADAPTERS[kind].parse_url(parsed, kind)


def adapter_for(ref: RepoRef, credential: Credential | None = None) -> SourceAdapter:
    return ADAPTERS[ref.host_kind](ref, credential)
