# Contributing

## Workflow

1. Branch from `main` and name it `<pod>/<short-desc>`, for example `ingest/gitlab-client`.
2. Install the hooks once: `uv run pre-commit install`. The hooks run ruff, gitleaks and basic checks.
3. Before you push, run `uv run poe check`. It runs the same lint, typecheck and tests as CI.
4. Open a PR and fill in the template checklist. CODEOWNERS picks the reviewers.

## Adding things

**A new backend** (for example `AzureSearchChunkStore`):
- Implement the `Protocol` from `rag_core.interfaces` in the package that owns it, and put any
  Azure SDKs behind the package's `azure` extra.
- Read the tenant with `require_tenant_id()`. Never add a `tenant_id` parameter.
- Register it by name in that service's wiring (`rag_api/deps.py`, `rag_ingest/worker.py`).
- Add the store to the tenancy leak tests.

**A new language parser:**
- Implement `ParserPlugin` in `rag_parsers/chunkers/` and register it in `default_registry()`.
- Chunks must be semantically whole and carry `symbol` and `signature`. Add tests.

**A new agent tool:**
- Add the request model to `rag_core/api_models.py`, then the route in
  `rag_api/routers/tools.py`, the SDK method, and the MCP tool, in that order. All three must
  keep the same shape.

**A ranking or chunking change:**
- Run `rag-eval` before and after, and attach the report to the PR.
- Bump `INDEX_VERSION` in `rag_core/schemas.py` if stored data changes.

## Code conventions

- Use `ruff format` with line length 100. Every package passes `mypy --strict`.
- Reference the design doc section in docstrings (`§7.1`) when the code implements it.
- Mark unfinished work as `TODO(<pod>): ...` so the backlog stays greppable:
  `rg "TODO\((ingestion|index|platform|eval)"`.
- Never log raw chunk text, query text or secret values. Log counts, types and IDs.
