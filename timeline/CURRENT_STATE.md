# Current state

_Last updated: 2026-10-28 (branch `goldan-repo-re-guru`, phase P4 of `plan/phases.md`; P0-P3 and the chunking part of P6 done)_

## What the app does today
A FastAPI web app (src layout, managed by `uv`, Python >=3.14). The user enters a GitHub or Azure DevOps repo
URL, a PAT and optionally a branch in a single-page UI. The backend (`services/connections.connect`; `routes.py` stays thin):

1. Parses the URL (`services/sources/registry.parse_repo_url`; the host's adapter owns the URL shape) into a host-aware `RepoRef`
   (`host_kind`, `host`, `path_parts`, `name`) with a `slug` such as `github.com__acme__golden`.
   GitHub, GitHub Enterprise and Azure DevOps hosts are accepted (`config.SUPPORTED_HOST_KINDS`); GitLab and
   Bitbucket URLs get a "not supported yet" error. ADO URLs (`dev.azure.com/{org}/{project}/_git/{repo}`, legacy
   `{org}.visualstudio.com`, project-less shorthand) normalize to host `dev.azure.com`, `path_parts=(org, project)`. The slug keys the `.env` token entry, the
   clone folder, the Qdrant collection and the registry rows, so the same owner/name on two hosts never collide.
2. Picks the host's `SourceAdapter` (`adapter_for(ref, PatCredential(token))`). Adapters: GitHub/GHE and Azure DevOps
   (PAT as Basic with an empty user); routes, validator and ingestion never call a host directly. `adapter.web_url` is the
   canonical repo URL rebuilt from the `RepoRef`; it is what gets stored (registry and `.env`), so userinfo, query strings
   and fragments the user typed are never kept.
3. **Resolves the tracked branch:** the branch typed in the form, else the repo's saved tracked branch, else
   `adapter.default_branch()`. Branch names are checked against `config.BRANCH_NAME_PATTERN` (no leading `-`, no `..`,
   etc.) before any host call, then `adapter.head_sha(branch)` gives a clear 404 if it does not exist.
4. Lists the root **at that branch** (`adapter.list_dir("", ref=branch)`) and validates the "golden repo" structure
   (`services/validator.find_missing`): files `policies.md`, `nomenclature.md`; folders `project-data/`, `templates/`
   (case-sensitive, defined in `config.py`). Missing items -> HTTP 422 listing them.
   As soon as that root listing succeeds (even if validation then fails) a typed PAT is saved to the git-ignored `.env`
   (`services/token_store.py`) with the cleaned URL; a blank token field reuses the saved one. Tokens are never returned by
   any API. Entries saved before P1 (`ASTRA_REPO_<OWNER>__<NAME>_*`) are moved to the host-aware key on first use.
5. **Registers the repo and queues a run in one SQLite transaction** (`registry.runs.queue_run`, `BEGIN IMMEDIATE`):
   if the repo already has a `queued`/`running` run the request gets **409** and nothing changes; otherwise the repo row is
   inserted or updated (a new branch bumps `config_version`) and a `queued` run is created.
6. Shallow-clones the tracked branch (`--depth 1 --branch <b> --single-branch`) into `temp_storage/<slug>/`
   (`services/cloner.py` replaces any earlier clone; `adapter.clone` via `sources/git.py`). The auth header goes through
   `GIT_CONFIG_*` env vars (not the URL, `.git/config` or process args). A clone failure finishes the run as `failed`.
7. Starts a **background ingestion** of `project-data/` (`services/ingestion/pipeline.run_ingestion(run_id, ...)`), which
   writes its progress to the run row: load (md, txt, csv, docx; others reported as skipped; symlinks, junctions and anything
   resolving outside the clone are never followed; the clone uses `core.symlinks=false`) -> chunk (markdown: **one chunk per heading section** with its own heading path, oversize sections split, tables/code fences kept whole, horizontal-rule lines `---` / `***` / `___` omitted from the text (decoration only, never a chunk boundary); CSV: **one chunk per row** + a small summary chunk; <=~480 est. tokens) -> embed locally with fastembed (dense `BAAI/bge-base-en-v1.5`,
   sparse `Qdrant/bm25`) -> upsert to Qdrant collection `astra__<slug>` (dropped and recreated each time; the run is flagged
   `index_replaced` just before the drop). Each chunk's payload has repo, repo_slug, host, commit_sha, path, folder_parts,
   heading_path / line range / row range (+ `row_key` for CSV), `doc_type` (from the folder),
   `doc_date` and `doc_meta` (parsed from email / meeting / CR / owner header lines, or the filename date), `has_open_item` /
   `open_items` ("Open: ...", "to decide"), file_hash, chunk ids, embedding model, ingested_at and a permalink `source_url`.

### Registry (`services/registry/`, SQLite at `data/astra.db`, override `ASTRA_DB_PATH`)
- `db.py`: one connection per operation with `foreign_keys=ON`, `busy_timeout`, WAL; explicit transactions;
  ordered migrations tracked in `PRAGMA user_version` (schema 1), applied in one transaction at startup. A database newer
  than the code is refused, never downgraded.
- Tables: `repos` (slug, cleaned url, host, `tracked_branch`, `config_version`, `credential_ref` = name of the `.env`
  key, never the token, and the last good build: `indexed_run_id/branch/commit_sha/collection/config_version/at`),
  `project_bindings` (`project_id` PK -> repo slug: one repo per project, a repo serves many), `ingestion_runs`.
- Only a `done` run writes the repo's `indexed_*` fields, and only if it is newer than the current indexed run; failed runs
  never touch them. `needs_rebuild` is derived: never indexed, index incomplete, or `indexed_config_version != config_version`
  (so a branch change during a run stays pending after that run succeeds).
- `index_state`: `rebuilding` (a run is active), `none`, `incomplete` (a later run dropped the collection and then failed:
  search may be empty or partial until a rebuild succeeds), `ready`.
- App lifespan (`registry.startup`): migrate, then mark runs left `queued`/`running` by a previous process as `failed`
  ("Interrupted by a server restart.").

Endpoints:
- `POST /api/validate-and-clone` (`url`, `token`, optional `branch`; returns `slug`, `branch`, `run_id`; 409 if a run is active)
- `GET /api/ingestion-status/{slug}` (latest run, from SQLite, survives restarts)
- `GET /api/repos` (tracked vs indexed branch/commit, `index_state`, `needs_rebuild`, last run, bound projects)
- `PUT /api/repos/{slug}/settings` (`tracked_branch`; checks the branch exists with the saved token; marks a rebuild)
- `PUT /api/projects/{project_id}/binding` (`repo_slug`), `GET /api/projects/{project_id}`
- `POST /api/search` (`slug` + `query`; hybrid RRF search; optional `folder`, `file_type` filters)

Page at `/` (connect form with a branch field, repos table), OpenAPI at `/docs`.

**No API authentication.** All endpoints, including the repo/project management ones, are open to whoever can reach the
server. Keep it on `127.0.0.1` (the default in `main()`) or behind a trusted proxy until API auth is built.

Qdrant runs in Docker (`docker-compose.yml`, v1.20.0, named volume). Embedding models download on
first use into `.cache/fastembed` (git-ignored).

Retrieval has **no recency or authority preference**: date and doc type are information only, search returns every hybrid
match and the LLM decides between conflicting sources.

## Not built yet
- P6 remainder: YAML front-matter parsing (`fm.*` payload fields).
- P5: nightly / Sync now, per-repo lock with coalescing, and **atomic index replacement** (versioned collections behind an
  alias). Until then a rebuild drops the live collection first, so search is empty during a rebuild and partial after a
  failed one (`index_state: incomplete`). A branch change waits for the next manual connect.
- W2 / P7-P9: function-calling tool returning policies + nomenclature + template from the host.
- Incremental re-ingest (currently full rebuild), pdf/xlsx loaders, reranking.
- API authentication; deleting repos or bindings.

## Layout
```
src/astra_rag/  __init__ (app factory + lifespan, main), config, routes
  services/     connections (connect, change branch), repo_ref, validator, cloner, token_store, errors
    registry/   db (connection, transactions, migrations), repos (repos + bindings), runs (ingestion runs), rules
    sources/    base (SourceAdapter port), credentials (PatCredential), registry (adapter lookup), github, azure_devops, git, http, json_reply, errors
    ingestion/  loader, md_chunker, csv_chunker, doc_meta, chunker, embedder, store, pipeline, models, tokens
  templates/ static/   UI
tests/          unittest suites + helpers (temp registry) + fixtures/repo; tests/sources/ holds the adapter contract suite
docker-compose.yml   Qdrant
data/           registry database (git-ignored)
temp_storage/   cloned repos (git-ignored)
timeline/       this progress record
plan/           design plans: golden-repo-rag-plan.md (requirements), phases.md (P0-P11 delivery order)
```

## Commands
- Qdrant: `docker compose up -d qdrant` (dashboard http://localhost:6333/dashboard)
- Run: `uv run python -m astra_rag` (http://127.0.0.1:5000)
- Test: `uv run python -m unittest discover -s tests -t .`
