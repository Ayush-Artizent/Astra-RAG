"""Shared fixtures for tool tests: a fake golden repo served through mocked github_client calls."""
from astra_rag.services.errors import AppError
from astra_rag.services.github_client import RepoRef

REPO = RepoRef("github.com", "acme", "golden")
PAT = "ghp_SECRET_TOKEN_123"
HANDLER = "astra_rag.services.tools.document_context.handler.github_client"
CREDS = "astra_rag.services.token_store.get_credentials"
ARGS = {"owner": "acme", "name": "golden"}

FILES = {
    "policies.md": "POLICIES", "nomenclature.md": "NAMES",
    "templates/brd.md": "BRD TEMPLATE", "templates/spec.md": "SPEC TEMPLATE",
}
TEMPLATES = [
    {"name": "brd.md", "type": "file"}, {"name": "spec.md", "type": "file"},
    {"name": ".gitkeep", "type": "file"}, {"name": "diagrams", "type": "dir"},
]


def fake_get_file(repo, path, token):
    if path not in FILES:
        raise AppError(f"File '{path}' was not found in the repository.", 404)
    return {"path": path, "sha": "sha-" + path, "content": FILES[path]}
