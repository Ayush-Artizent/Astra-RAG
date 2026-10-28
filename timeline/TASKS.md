# Tasks

Status: `[ ]` todo · `[~]` doing · `[x]` done. Update status and add a CHANGELOG line as you go.

> **Next work follows [plan/phases.md](../plan/phases.md) (P0-P11), one phase per PR.** The W2 and W4 lists below are
> folded into those phases (W2 → P7-P9, W4 → P4-P5) and are kept for history.

## Phases (from plan/phases.md)
- [x] **P0 Safety fixes and doc cleanup** - loader never follows symlinks/junctions or paths outside the clone; clone uses `core.symlinks=false`; docs fixed. (2026-10-28)
- [x] **P1 Host-aware repo identity** - `services/repo_ref.py` (`RepoRef` + host-aware `slug`); slug keys token store, clone folder, Qdrant collection and status; legacy `.env` keys migrated; non-GitHub hosts rejected as not supported yet; status/search routes take the slug. (2026-10-28)
- [x] **P2 Source adapter port + GitHub adapter** - `services/sources/` (`SourceAdapter` port, `PatCredential`, registry, GitHub adapter, shared git/http/error helpers) with a reusable contract test suite; routes, validator, cloner and chunker go through the adapter; `github_client.py` removed. No behaviour change. (2026-10-28)
- [x] **P3 Azure DevOps adapter** - `services/sources/azure_devops.py` (URL forms, REST 7.1, Basic auth, citation links, 203 sign-in page -> 401) passes the contract suite; registered in `registry.ADAPTERS` and `config.SUPPORTED_HOST_KINDS`. Open: real-repo check (line-highlight links, case behaviour). (2026-10-28)
- [ ] P4 Repo registry, bindings and tracked branch
- [ ] P5 Sync: nightly + Sync now, alias swap
- [~] **P6 Structure- and metadata-aware ingestion** - done 2026-10-28: per-section markdown chunks, per-row CSV chunks (`row_key`), header metadata (`doc_type`, `doc_date`, `doc_meta`), open-item flags, no recency preference, horizontal rules (`---`) omitted. Todo: YAML front-matter (`fm.*`, stripped from text, bad-YAML warning).
- [ ] P7 Golden catalog
- [ ] P8 Rule selection and request inference
- [ ] P9 `get_context` API, sub-queries, rerank, tools
- [ ] P10 GitLab and Bitbucket adapters
- [ ] P11 Evaluation set and tuning

## Done
- [x] **W0 Connector** - URL parse, GitHub root listing, golden-structure validation, clone to `temp_storage/`.
- [x] **W1 Ingestion pipeline** - see W1 below.
- [x] **W3 Timeline + rules** - `timeline/` folder and root `CLAUDE.md`.

## W1 - RAG ingestion pipeline (runs after clone succeeds)
Goal: once the clone finishes, automatically chunk `project-data/` and store hybrid embeddings in Qdrant,
with metadata that traces every chunk back to repo / commit / file / location.
Independent of W2 except both add deps to `pyproject.toml` and a config section.

**Decisions (design approved 2026-10-27)**
- Vector DB: **Qdrant in Docker on Rancher Desktop** (server mode, named volume, `QDRANT_URL` in config). No embedded mode.
- Embeddings, local via `fastembed`, auto-downloaded on first use: dense `BAAI/bge-base-en-v1.5` (768-d) + sparse `Qdrant/bm25`, hybrid query fused with RRF. Behind an `Embedder` interface.
- Index only `project-data/` (md, csv, docx). Policies, nomenclature and templates go through the W2 tool, not the index.
- Chunking is token-budgeted for bge's 512-token limit (target ~350-400, cap ~480): markdown/docx by heading with breadcrumb prefix; CSV by row groups with header repeated + one summary chunk per file.
- One collection per repo (`astra__<owner>__<name>`); re-ingest = delete + recreate. Point id = UUIDv5(chunk_id).
- Payload metadata: repo, commit_sha, path, folder_parts, file_type, file_hash, chunk ids, heading_path, line or row range, embedding_model, ingested_at, GitHub permalink `source_url`.

- [x] W1.1 Smoke test on Python 3.14: `uv add qdrant-client fastembed`, embed + upsert + hybrid query against Dockerised Qdrant. Result: works on 3.14 (fastembed 0.9.1, onnxruntime 1.31, qdrant-client 1.20 vs server v1.20.0). If `onnxruntime` lacks a 3.14 wheel, decide: pin lower Python or switch embedder. Then add settings to `config.py`.
- [x] W1.2 Infra - `docker-compose.yml` (pinned `qdrant/qdrant`, ports 6333/6334, named volume); `QDRANT_URL` / `QDRANT_API_KEY` / `FASTEMBED_CACHE_DIR` in `config.py`; git-ignore caches. Capture commit SHA in `cloner.py` (`git rev-parse HEAD`).
- [x] W1.3 `services/ingestion/loader.py` - walk `project-data/**`, load md/txt/csv/docx (docx via markitdown or mammoth), skip `.git`, binaries, empty and oversized files; unsupported types reported in the ingestion report, not silently dropped.
- [x] W1.4 `services/ingestion/chunker.py` - markdown/docx and CSV chunkers as above; never split code fences or tables; deterministic `chunk_id = sha1(path + index + sha1(content))`; full metadata per chunk.
- [x] W1.5 `services/ingestion/embedder.py` + `store.py` - dense + sparse embeddings in batches; Qdrant collection with named vectors and keyword payload indexes (`path`, `folder_top`, `file_type`, `file_hash`, `commit_sha`); upsert; hybrid search; delete/recreate. Clear `AppError` if Qdrant is unreachable.
- [x] W1.6 Trigger + status - `pipeline.py`; start ingestion as a background task at the end of `validate_and_clone` (don't block the response); `GET /api/ingestion-status` (queued/running/done/failed, chunk counts, skipped files); show progress in the UI.
- [x] W1.7 Tests - fixtures in `tests/fixtures/project-data/` (nested md/csv/docx); chunk size caps, intact code fences/tables, CSV header repeated, deterministic ids, complete metadata; store test using `QdrantClient(":memory:")`; no network or model downloads in unit tests (fake embedder).

**Status: implemented and verified 2026-10-27** (30 unit/route tests; real-model + real-Qdrant e2e: max chunk 327 real bge tokens, exact-ID and paraphrase queries hit the right source).

**Open items:** whether `.pdf`/`.xlsx` will appear in `project-data/`; largest CSV size (row caps); bge-base vs bge-small if speed becomes an issue.

**Follow-ups noticed:** token estimate is conservative (est. cap 480 -> ~330 real); could be tuned using the real tokenizer. No incremental re-ingest (full rebuild each time). `POST /api/search` was added to exercise retrieval; W2/generation will build on it.

## W2 - Function-calling tool: fetch policies + template from GitHub
Goal: an LLM-callable tool; when invoked with a request type (BRD, SPEC, ...), it returns
`policies.md` plus the matching template, read **directly from GitHub** (not the local clone).

- [ ] W2.1 Define the template convention: map request type -> file in `templates/` (e.g. `BRD` -> `templates/brd.md`). Check `nomenclature.md` for naming rules first; put the mapping/aliases in `config.py`. **Open question for the user:** exact template filenames in the golden repo.
- [ ] W2.2 Read files with `SourceAdapter.read_file` (added in P2; was `github_client.get_file`) (GitHub contents API, base64 decode, size guard, clear errors for 404/403).
- [ ] W2.3 `services/tools/document_context.py` - the tool function `get_document_context(request_type)` -> `{request_type, policies, nomenclature, template}`, all fetched whole from GitHub at call time (deterministic, **not** via RAG: these are small authoritative rulebooks that must always apply in full). Unknown type returns an error listing valid types (derive valid types by listing `templates/` from GitHub). If `nomenclature.md` proves very large (>~15k tokens), split by section and return only relevant sections.
- [ ] W2.3b Nomenclature validator (`services/tools/nomenclature.py`) - once the format of `nomenclature.md` is known (prose vs pattern table), add a check that a generated document name/ID matches its rules (e.g. regex per doc type). The LLM applies the rule; code verifies it. **Open question:** format of `nomenclature.md`.
- [ ] W2.4 Tool schema + dispatcher (`services/tools/registry.py`): JSON schema (name, description, `request_type` enum) in Claude tool-use format, and a `run_tool(name, args)` dispatcher.
- [ ] W2.5 Wiring - choose the surface: a `POST /api/tools/invoke` endpoint and/or an agent loop that passes the schema to the Claude API and feeds tool results back. Repo comes from the request; the token comes from `token_store.get_token(repo)` (saved in the git-ignored `.env`), never from the LLM and never returned.
- [ ] W2.6 Tests - mock the GitHub client; cover each request type, unknown type, missing template, missing policies.md or nomenclature.md, and the nomenclature validator.

## W4 - Keep the index in sync with the repo's main branch (planned, not started)
Goal: when someone pushes to the tracked branch, re-embed only what changed so Qdrant always reflects the latest
`project-data/`, and every chunk's `commit_sha` / `source_url` points at the latest commit. Changes to
`policies.md`, `nomenclature.md` and `templates/` need nothing (W2 reads them live from GitHub).

**Decisions:** trigger = GitHub `push` webhook (primary) + polling reconciliation (safety net, also the localhost
default). Sync = hash-diff against stored `file_hash` (robust to force-pushes), upsert-then-delete so searches never
see a file missing mid-sync, full rebuild as fallback. Sync state is persisted (SQLite behind a `SyncStateStore`).
Design detail: `C:\Users\manojb\.claude\plans\i-am-thinking-we-distributed-cook.md` (author's machine).

- [ ] W4.1 State + locks - `services/ingestion/state.py` (durable per-repo `last_commit_sha`, `last_synced_at`, state, error) and `locks.py` (per-repo exclusion, coalesce bursts of triggers into one re-run). Config: `SYNC_POLL_SECONDS`, `GITHUB_WEBHOOK_SECRET`, `CHUNKER_VERSION` (stored in payload to force a rebuild when chunking rules change).
- [ ] W4.2 Store + git + GitHub helpers - `store.py`: `file_hashes()`, `ids_for_path()`, `delete_points()`, `delete_path()`, `bump_commit()`; `cloner.update_clone()` (`git fetch --depth 1` + hard reset, token via env vars); `SourceAdapter.head_sha()` (exists since P2; add ETag) (304 is free against rate limits).
- [ ] W4.3 Sync engine - `services/ingestion/sync.py`: update clone, chunk locally, classify added / changed / deleted / unchanged, embed only added + changed, delete stale chunks, bump `commit_sha` + permalink on unchanged chunks, persist state; fall back to full rebuild if the collection is missing or model / dimension / chunker version changed. Refactor `pipeline.py` so full ingest and sync share the embed + upsert step.
- [ ] W4.4 Triggers - `POST /api/webhooks/github` (HMAC-SHA256 `X-Hub-Signature-256` check, push events on the tracked branch only, 202 fast, dedupe by delivery id); background poller thread started in the app lifespan; `POST /api/sync/{owner}/{name}` ("Sync now").
- [ ] W4.5 UI + status - show last synced commit / time and a Sync now button; sync info in `GET /api/ingestion-status`.
- [ ] W4.6 Tests - unchanged file => zero embed calls but `commit_sha` bumped; edit / delete / rename cases; no missing file mid-sync; concurrent triggers coalesce; webhook signature valid / invalid / non-main push; poller 304 and new-SHA paths; fallback rebuild. Tests must use temp state DB and in-memory Qdrant (never the real `.env` or `.cache`).
- [ ] W4.7 End-to-end on real Qdrant - push an edit and a deletion to a test repo, confirm search returns new text, deleted file is gone, point count matches, `source_url` uses the new SHA, and state survives a restart.

**Later (not in W4):** GitHub App credentials instead of PATs (short-lived tokens, higher rate limits); shared DB for sync state if run on several instances.

## Sequencing
W1 and W2 can proceed in parallel (separate packages under `services/`, different routes).
Shared touch points to coordinate: `pyproject.toml`, `config.py`, `routes.py`, `timeline/*`.
