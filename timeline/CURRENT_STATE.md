# Current state

_Last updated: 2026-10-28 (branch `goldan-repo-re-guru`, phase P5 of `plan/phases.md`; P0-P4 and the chunking part of P6 done)_

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
5. **Registers the repo and queues a forced sync in one SQLite transaction** (`registry.runs.register_and_queue`,
   `BEGIN IMMEDIATE`). Only a real change of tracked branch bumps `config_version`; the source error is cleared (the host
   just accepted the token). If a run is already active, nothing new starts: the request is **coalesced** into one
   follow-up run (`sync_pending`/`sync_force` on the repo) and the response says `pending` (P4 answered 409 here).
   The response carries the branch head seen while connecting; the clone happens in the background, not in the request.
6. **The sync worker** (`services/sync/service.execute`, on a one-thread pool owned by the app lifespan) shallow-clones the
   tracked branch (`--depth 1 --branch <b> --single-branch`) into `temp_storage/<slug>/` (`services/cloner.py`;
   `adapter.clone` via `sources/git.py`; auth header via `GIT_CONFIG_*` env vars, not the URL, `.git/config` or process
   args). A clone failure finishes the run as `failed` and records `source_error` on the repo.
7. Then ingests `project-data/` (`services/ingestion/pipeline.run_ingestion(run_id, ...)`), writing progress to the run
   row: load (md, txt, csv, docx; others reported as skipped; symlinks, junctions and anything resolving outside the clone
   are never followed; the clone uses `core.symlinks=false`) -> chunk (markdown: **one chunk per heading section** with its own heading path, oversize sections split, tables/code fences kept whole, horizontal-rule lines `---` / `***` / `___` omitted from the text (decoration only, never a chunk boundary); CSV: **one chunk per row** + a small summary chunk; <=~480 est. tokens) -> embed locally with fastembed (dense `BAAI/bge-base-en-v1.5`, sparse `Qdrant/bm25`) ->
   upsert into a **new version collection** `astra_v<run id>__<slug>` -> check the point count -> switch the alias
   `astra__<slug>` to it in one `update_collection_aliases` call -> drop older versions. Search always reads the alias, so
   it keeps serving the previous build during a rebuild and after a failed one (the half-built version is deleted).
   Each chunk's payload has repo, repo_slug, host, commit_sha, path, folder_parts,
   heading_path / line range / row range (+ `row_key` for CSV), `doc_type` (from the folder),
   `doc_date` and `doc_meta` (parsed from email / meeting / CR / owner header lines, or the filename date), `has_open_item` /
   `open_items` ("Open: ...", "to decide"), file_hash, chunk ids, embedding model, ingested_at and a permalink `source_url`.
8. When a run ends, a coalesced follow-up (if any) is checked and started.

### Sync (`services/sync/`)
- `request_sync(slug, triggered_by, force)`: unless forced or a run is active, calls `adapter.head_sha(tracked_branch)`
  with the saved token; unchanged head + no config change -> `up_to_date` (no run row); otherwise queues a run (or
  coalesces). Host failures set the repo's `source_error` (401 -> "reconnect with a new PAT"); the old index keeps serving.
- Triggers: connect (forced), **Sync now** (`POST /api/repos/{slug}/sync`), a branch change in settings (forced),
  the **nightly check** at `SYNC_DAILY_AT` UTC (`scheduler.py`, daemon thread; env `ASTRA_SYNC_DAILY_AT`), and a
  **startup catch-up** for repos not checked for `SYNC_CATCHUP_HOURS` or waiting for a follow-up.
- **Single instance** (`instance.py`): the lifespan takes an exclusive OS lock on `<data dir>/astra.lock`; a second
  instance on the same data directory fails at startup. Order: lock -> migrate + sweep -> recovery -> worker -> scheduler.
- **Startup recovery** (`reconcile.py`, also before each nightly pass): compares each repo's alias target with the
  registry. A completed swap whose run was never recorded (crash between the alias switch and `finish_run`) is adopted
  (`runs.adopt_run`); an unknown or missing target asks for a forced rebuild; orphan versions are dropped. Deletes go
  through `store.delete_version`, which never deletes the collection the alias serves. Skipped (logged) if Qdrant is down.
- `ASTRA_SYNC_SCHEDULER=0` turns off the nightly check, catch-up and startup recovery (tests set it).
- Logs and stored errors carry only `AppError` messages or exception type names, never the token or host replies.

### Registry (`services/registry/`, SQLite at `data/astra.db`, override `ASTRA_DB_PATH`)
- `db.py`: one connection per operation with `foreign_keys=ON`, `busy_timeout`, WAL; explicit transactions;
  ordered migrations tracked in `PRAGMA user_version` (schema 2), applied in one transaction at startup. A database newer
  than the code is refused, never downgraded. Schema 2 (P5) adds `repos.sync_pending/sync_force/last_checked_at/
  source_error` and `ingestion_runs.triggered_by`.
- Tables: `repos` (slug, cleaned url, host, `tracked_branch`, `config_version`, `credential_ref` = name of the `.env`
  key, never the token, and the last good build: `indexed_run_id/branch/commit_sha/collection/config_version/at`),
  `project_bindings` (`project_id` PK -> repo slug: one repo per project, a repo serves many), `ingestion_runs`.
- Only a `done` run writes the repo's `indexed_*` fields, and only if it is newer than the current indexed run; failed runs
  never touch them. `needs_rebuild` is derived: never indexed, index incomplete, or `indexed_config_version != config_version`
  (so a branch change during a run stays pending after that run succeeds).
- `index_state`: `rebuilding` (a run is active), `none`, `incomplete` (only for runs from before P5, which dropped the
  live collection first), `ready`. `sync_status`: `syncing | queued | pending | source_error | never_indexed |
  out_of_date | up_to_date`, plus `sync: {last_checked_at, pending, source_error}` in the repo view.
- App lifespan (`registry.startup`): migrate, then mark runs left `queued`/`running` by a previous process as `failed`
  ("Interrupted by a server restart.").

Endpoints:
- `POST /api/validate-and-clone` (`url`, `token`, optional `branch`; returns `branch`, `commit_sha` (head at connect),
  `ingestion: {slug, run_id, state: queued | pending}`; no clone path, no 409)
- `GET /api/ingestion-status/{slug}` (latest run, from SQLite, survives restarts; includes `triggered_by`)
- `GET /api/repos` (tracked vs indexed branch/commit, `index_state`, `needs_rebuild`, `sync_status`, `sync`, last run,
  bound projects; top-level `schedule: {enabled, daily_at_utc, next_check_at}`)
- `POST /api/repos/{slug}/sync` (Sync now: `up_to_date` + `commit_sha` / `queued` + `run_id` / `pending`)
- `PUT /api/repos/{slug}/settings` (`tracked_branch`; checks the branch exists with the saved token, then starts a rebuild)
- `PUT /api/projects/{project_id}/binding` (`repo_slug`), `GET /api/projects/{project_id}`
- `POST /api/search` (`slug` + `query`; hybrid RRF search; optional `folder`, `file_type` filters)

Page at `/` (connect form with a branch field; repos table with indexed commit and time, last checked, sync status,
a Sync now button per repo and a line with the next nightly check), OpenAPI at `/docs`.

**No API authentication.** All endpoints, including repo/project management and Sync now, are open to whoever can reach
the server. Keep it on `127.0.0.1` (the default in `main()`) or behind an authenticating reverse proxy; never expose it
directly to the internet. **One instance per data directory** (enforced by the lock); no `--workers` > 1.

Qdrant runs in Docker (`docker-compose.yml`, v1.20.0, named volume). Embedding models download on
first use into `.cache/fastembed` (git-ignored).

Retrieval has **no recency or authority preference**: date and doc type are information only, search returns every hybrid
match and the LLM decides between conflicting sources.

## Not built yet
- P6 remainder: YAML front-matter parsing (`fm.*` payload fields).
- Webhooks (instant updates; needs a public URL and per-repo setup by the customer) and hash-diff incremental ingest.
- Several app instances (needs shared scheduling and a shared database).
- W2 / P7-P9: function-calling tool returning policies + nomenclature + template from the host.
- Incremental re-ingest (currently full rebuild), pdf/xlsx loaders, reranking.
- API authentication; deleting repos or bindings.

## Layout
```
src/astra_rag/  __init__ (app factory + lifespan, main), config, routes
  services/     connections (connect, change branch), repo_ref, validator, cloner, token_store, errors
    registry/   db (connection, transactions, migrations), repos (repos + bindings), runs (ingestion runs), rules
    sync/       service (check, queue, clone, ingest, follow-up), worker, scheduler (nightly + catch-up), reconcile
                (startup recovery), instance (single-instance lock)
    sources/    base (SourceAdapter port), credentials (PatCredential), registry (adapter lookup), github, azure_devops, git, http, json_reply, errors
    ingestion/  loader, md_chunker, csv_chunker, doc_meta, chunker, embedder, store, pipeline, models, tokens
  templates/ static/   UI
tests/          unittest suites + helpers (temp registry) + fixtures/repo; tests/sources/ holds the adapter contract suite
docker-compose.yml   Qdrant
data/           registry database + instance lock (git-ignored)
temp_storage/   cloned repos (git-ignored)
timeline/       this progress record
plan/           design plans: golden-repo-rag-plan.md (requirements), phases.md (P0-P11 delivery order)
```

## Commands
- Qdrant: `docker compose up -d qdrant` (dashboard http://localhost:6333/dashboard)
- Run: `uv run python -m astra_rag` (http://127.0.0.1:5000)
- Test: `uv run python -m unittest discover -s tests -t .`
