# Astra RAG: notes for Claude Code

Multi-tenant RAG retrieval service, structured as a uv workspace monorepo. Start with `README.md` and
`docs/architecture.md`. Section numbers (§) in the code refer to the design doc linked in the README.

## Commands

- `uv sync` installs everything. `uv run poe check` runs lint, mypy --strict and pytest. CI runs the same.
- Run a single test with `uv run pytest services/rag-api/tests/test_api.py -k leak`.
- Run the API locally with `uv run poe api`. It starts on :8080 with memory backends and a demo corpus.
  The dev bearer tokens are `dev-key-tenant-a` and `dev-key-tenant-b`.

## Rules that must hold

- Never add a `tenant_id` parameter to stores, or a `tenant_id` field to request models. The
  tenant comes from `rag_core.tenancy` (credential → `TenantContext` → `tenant_scope`).
- Text gets redacted (`rag_core.redaction`) before it is chunked, embedded, logged or traced.
  If redaction fails, the file is skipped.
- Every retrieval result carries a `Citation`. Responses include `trace_id` and `snapshot`.
- Shared request and response shapes live in `rag_core` (`schemas.py`, `api_models.py`). REST, MCP and
  the SDK must stay identical.
- Ranking or chunking changes need an eval run (`rag-eval`), and an `INDEX_VERSION` bump if
  stored data changes.
- Mark unfinished work as `TODO(<pod>): ...`. The pods are ingestion, index-retrieval, platform and eval.
