# Tasks

Status: `[ ]` todo · `[~]` doing · `[x]` done. Update status and add a CHANGELOG line as you go.

## Done
- [x] **W0 Connector** - URL parse, GitHub root listing, golden-structure validation, clone to `temp_storage/`.
- [x] **W3 Timeline + rules** - `timeline/` folder and root `CLAUDE.md`.

## W1 - RAG ingestion pipeline (runs after clone succeeds)
Goal: once the clone finishes, automatically chunk the repo content and store embeddings.
Independent of W2 except both add deps to `pyproject.toml` and a config section.

- [ ] W1.1 Decide stack (embedding model + vector store, e.g. local sentence-transformers + Chroma/FAISS, or API embeddings). Record the decision in CHANGELOG. Add settings to `config.py`.
- [ ] W1.2 `services/ingestion/loader.py` - walk the clone, load `.md`/text files from `project-data/` (+ `policies.md`, `nomenclature.md`, `templates/`), skip `.git`, binaries, oversized files. Attach metadata (relative path, folder, repo, commit).
- [ ] W1.3 `services/ingestion/chunker.py` - markdown-aware chunking (split on headings, then size/overlap cap); deterministic chunk IDs.
- [ ] W1.4 `services/ingestion/embedder.py` + `store.py` - embed chunks in batches and upsert into a per-repo collection; re-ingest replaces the old collection (mirrors clone replace behaviour).
- [ ] W1.5 Trigger + status - start ingestion as a background task at the end of `validate_and_clone` (don't block the HTTP response); add `GET /api/ingestion-status` (queued/running/done/failed, chunk counts); show progress in the UI.
- [ ] W1.6 Tests - loader/chunker unit tests with fixture files; store test with a temp directory; no network.

## W2 - Function-calling tool: fetch policies + template from GitHub
Goal: an LLM-callable tool; when invoked with a request type (BRD, SPEC, ...), it returns
`policies.md` plus the matching template, read **directly from GitHub** (not the local clone).

- [ ] W2.1 Define the template convention: map request type -> file in `templates/` (e.g. `BRD` -> `templates/brd.md`). Check `nomenclature.md` for naming rules first; put the mapping/aliases in `config.py`. **Open question for the user:** exact template filenames in the golden repo.
- [ ] W2.2 Extend `services/github_client.py` with `get_file(repo, path, token)` (GitHub contents API, base64 decode, size guard, clear errors for 404/403).
- [ ] W2.3 `services/tools/document_context.py` - the tool function `get_document_context(request_type)` -> `{policies, template, request_type}`; unknown type returns an error listing valid types (derive valid types by listing `templates/` from GitHub).
- [ ] W2.4 Tool schema + dispatcher (`services/tools/registry.py`): JSON schema (name, description, `request_type` enum) in Claude tool-use format, and a `run_tool(name, args)` dispatcher.
- [ ] W2.5 Wiring - choose the surface: a `POST /api/tools/invoke` endpoint and/or an agent loop that passes the schema to the Claude API and feeds tool results back. Repo/token come from the session/request, never persisted.
- [ ] W2.6 Tests - mock the GitHub client; cover each request type, unknown type, missing template, missing policies.md.

## Sequencing
W1 and W2 can proceed in parallel (separate packages under `services/`, different routes).
Shared touch points to coordinate: `pyproject.toml`, `config.py`, `routes.py`, `timeline/*`.
