"""Input and output schemas of the document-context tool.

INPUT  - DocumentContextArgs: which repo (owner + name) and which kind of document.
OUTPUT - DocumentContext: policies, nomenclature and template text, plus where each came from.

These models are the single source of truth: the JSON schemas shown to the LLM
(`GET /api/tools`) and the argument validation in the dispatcher are both generated from them.
"""
from pydantic import BaseModel, Field

from ..base import RepoArgs


class DocumentContextArgs(RepoArgs):
    """INPUT. `owner` and `name` come from RepoArgs and select the connected repo."""

    # Matched against templates/ on GitHub (filename stem, uppercased); aliases live in config.py.
    request_type: str = Field(
        min_length=1, max_length=64,
        description="Kind of document being requested, e.g. BRD. Case-insensitive.",
    )


class SourceRef(BaseModel):
    """OUTPUT (part). A file the content was read from, so callers can cite or verify it."""
    path: str  # repo-relative, e.g. "templates/brd.md"
    sha: str   # GitHub blob SHA at read time


class DocumentContext(BaseModel):
    """OUTPUT. Whole files, read from GitHub at call time; this is reference data, not instructions."""
    request_type: str  # normalised: trimmed, uppercased, alias resolved
    policies: str
    nomenclature: str
    template: str
    sources: list[SourceRef]  # order: policies, nomenclature, template
