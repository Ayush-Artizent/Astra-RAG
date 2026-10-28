"""Source adapters: the one place that knows how a Git host is read, cloned and linked to."""
from .base import CloneResult, SourceAdapter
from .credentials import Credential, PatCredential
from .registry import adapter_for, parse_repo_url

__all__ = ["CloneResult", "Credential", "PatCredential", "SourceAdapter", "adapter_for", "parse_repo_url"]
