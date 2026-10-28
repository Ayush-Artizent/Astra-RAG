# Changelog (newest first)

## 2026-10-28
- **P1 done (host-aware identity):** new `services/repo_ref.py` holds `RepoRef{host_kind, host, path_parts, name}` and a slug that includes the host (`github.com__acme__golden`), so the same owner/name on two hosts can no longer share a token, clone folder, collection or status. Old `.env` keys are migrated on first use (only when their saved URL is the same repo). Azure DevOps, GitLab and Bitbucket URLs now get a clear "not supported yet" error. **API change:** `GET /api/ingestion-status/{slug}` and `POST /api/search {slug, ...}` replace owner/name. Existing Qdrant collections and `temp_storage/` folders under old names are simply rebuilt on the next connect. Tests: 49 (1 skipped on Windows).
- **P0 done (security):** the loader now walks `project-data/` with `Path.walk` and never follows symlinks, Windows junctions or any path resolving outside the clone; it reports them as skipped instead. A golden repo could otherwise have exposed the `.env` holding PATs through search. `cloner.py` also clones with `core.symlinks=false`. Docs fixed (branch name, `token_store` in layout, TASKS W2.5 token wording). Tests: 42 (1 skipped on Windows; the file-symlink case was verified on Linux in Docker).
- Planning: added `plan/phases.md`, the delivery phases P0-P11 (safety fixes, host-aware identity, source adapters with ADO first, registry, sync, front-matter, catalog, rule selection, `get_context`, more hosts, eval). One phase per PR; nothing built yet.
- Planning: added `plan/golden-repo-rag-plan.md`, the end-to-end Golden Repo RAG requirements and plan (contract, rules model, inference, ADO-first source adapters, branch/sync, ingestion, retrieval). Draft for team discussion; no code changes.

## 2026-10-27
- Planning: added W4 (keep the index in sync with the repo's main branch) to `TASKS.md`; design agreed, no code written.
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
