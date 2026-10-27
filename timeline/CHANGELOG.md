# Changelog (newest first)

## 2026-10-27
- **Tools restructured** (no behaviour change): each LLM tool is a directory (`services/tools/document_context/{schemas,handler,__init__}.py`) exporting one `Tool`; `tools/base.py` has `Tool`, the `RepoArgs` (owner + name) base and `to_claude` / `to_mcp` renderers; `tools/registry.py` has the explicit `TOOLS` table with a generic dispatcher and `describe_tools`. `GET /api/tools` now also returns `output_schema`. Tests split into `tests/tools/` + `tests/test_github_and_credentials.py`. Tests: 66 passing.
- **W2 implemented**: LLM tool `get_document_context(owner, name, request_type)` returns `policies.md`, `nomenclature.md` and the matching `templates/*.md` read live from GitHub (`services/tools/`), with blob SHAs as sources. URL + PAT are looked up in `.env` by the existing `ASTRA_REPO_<OWNER>__<NAME>_*` convention (`token_store.get_credentials`), never taken from the caller. `github_client` gained `list_dir` / `get_file` (size guard, UTF-8, clear 404/403/401 errors). New endpoints `POST /api/tools/invoke`, `GET /api/tools`. `config.py` now has a pydantic-settings `Settings` (Qdrant/fastembed env, also read from `.env`) plus `TEMPLATES_FOLDER`, `TEMPLATE_EXTENSIONS`, `TEMPLATE_ALIASES`, `TOOL_MAX_FILE_BYTES`; `.env.example` added (and un-ignored). No auth yet. Tests: 64 passing.
- **PAT + URL now remembered in `.env`** (git-ignored): `services/token_store.py` writes `ASTRA_REPO_<OWNER>__<NAME>_URL/_TOKEN` after a connect that cloned successfully; a blank token field reuses the saved one; the token is cleared from the page and never returned by any API. `cloner.py` now passes the token to git through `GIT_CONFIG_*` env vars instead of `-c` args (no longer visible in the process list; verified against a local HTTP server). `CLAUDE.md` security rule updated accordingly. Tests: 38 passing.
- **W1 implemented**: after a successful clone, `project-data/` is ingested in the background (`services/ingestion/`): loader (md/txt/csv/docx, skipped files reported), heading-aware markdown chunker and row-aware CSV chunker (token-budgeted for bge's 512 limit), local fastembed embeddings (dense `BAAI/bge-base-en-v1.5` + sparse `Qdrant/bm25`), Qdrant collection per repo (`astra__<owner>__<name>`, hybrid RRF search, recreated on re-ingest). Chunk payloads carry repo, commit SHA, path, heading path / line or row range, file hash and a GitHub permalink.
- New endpoints `GET /api/ingestion-status/{owner}/{name}` and `POST /api/search`; UI polls ingestion progress. `clone_repo` now returns `CloneResult(path, commit_sha, branch)`.
- Added `docker-compose.yml` (Qdrant v1.20.0, named volume), deps `qdrant-client`, `fastembed`, `markitdown[docx]`, config for Qdrant/model/chunk sizes, `.cache/` ignored. Tests: 30 passing.
- Planning: W1 design approved - Qdrant (Docker/Rancher Desktop), fastembed hybrid (bge-base-en-v1.5 dense + BM25 sparse), type-aware token-budgeted chunking, traceable payload metadata. W1 tasks rewritten in `TASKS.md`; no code yet.
- Planning: W2 tool now also returns `nomenclature.md` (deterministic fetch, not RAG) and gains a nomenclature validator task; W1 noted as leaning Qdrant and scoped to `project-data/` only, pending further discussion.
- Added `timeline/` progress folder, `CLAUDE.md` project rules and the task breakdown (`TASKS.md`).

## 2026-10-26
- Switched project to `uv` (`uv.lock`, `.python-version`).
- Migrated to `src/astra_rag` layout with `uv_build` backend and `astra-rag` script.
- Added repo connector: URL parsing, GitHub root listing, mandatory-structure validation,
  token-safe shallow clone into `temp_storage/`, UI, and unit tests.

## 2026-10-12 / 2026-10-09
- Initial commit and refactor for readability (pre-connector scaffolding).
