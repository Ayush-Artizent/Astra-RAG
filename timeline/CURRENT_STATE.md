# Current state

_Last updated: 2026-10-30 (branch `goldan-repo-re-manoj`, P5 merged in: P0-P5 and the chunking part of P6 done, P7 and P8 done; see `plan/phases.md`)_

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
- `GET /api/projects/{project_id}/catalog` and `GET /api/repos/{slug}/catalog` (live catalog of rules and templates on the
  tracked branch; `?include_text=true` adds rule text; 404 unbound / unregistered, 400 no saved token)
- `POST /api/context/preview` (`project_id`, `doc_type`, optional `stage`, `tags`: the selected rules and the whole template;
  422 unknown doc type, 404 unbound project, 400 no saved token)
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

## Golden catalog (P7, done)
`services/catalog/` builds a catalog of the rules and templates outside `project-data/` from a `SourceReader`
(`head_sha`, `list_dir`, `read_file`); the endpoints above call it through `catalog/service.py`. It only lists and
warns; choosing rules for a request is `services/context` (P8, below).
- `manifest.py`: parses the optional root `golden.yaml` v1 (`doc_types` + aliases, `stages`, `tags`, `rules`, `templates`,
  `project_data`). Bad YAML or wrong shapes give warnings and fall back to conventions, never errors.
- `sections.py`: splits a markdown file into heading sections with stable ids (`policies.md#data-handling/retention`);
  headings in code fences are ignored; a heading with no body makes no section; a leading YAML front-matter block is skipped.
- `templates.py`: finds `templates/<type>.md` and `templates/<type>/<variant>.md`, reads each heading list; a flat file or the
  only variant is the default when the manifest names none.
- `catalog.py`: rule files are `policies.md`, `nomenclature.md` and `rules/**.md`. Each rule entry (`file`, optional `section`,
  `always` or `applies_to`, `priority`) sets a section's `selection` to `always` / `scope` (children inherit a parent
  heading's scope); every other section stays `relevance`. `CatalogCache` rebuilds only when the head sha changes and
  keeps file bodies by blob sha. Warnings: `required_missing`, `rule_file_missing`, `rule_section_missing`, `rule_no_scope`,
  `unknown_doc_type`, `template_missing`, `no_templates`, `no_default_variant`, `no_always_rules`, `manifest_*`.
- `local.py`: `LocalCloneReader` reads a local clone (no symlinks, nothing outside the clone).
- `live.py`: `AdapterReader` reads a repo through a `SourceAdapter` on the tracked branch. It looks up the head once and
  pins every read to that commit (a consistent snapshot; `head_sha` is exactly what was read). A missing file is `None`, a
  missing folder is empty, files over `MAX_CATALOG_FILE_BYTES` are skipped, other host errors propagate.
- `service.py`: `catalog_for_project` / `catalog_for_repo` look up the repo (P4 registry), its saved token and tracked branch,
  and go through one process-wide `CatalogCache` keyed `slug@branch`. If the host is unreachable and an earlier catalog
  exists it is returned with `stale: true`; with nothing cached the host error is returned.
- Adapters: `DirEntry` has an optional `sha` (GitHub `sha`, Azure DevOps `objectId`), so unchanged files are not re-downloaded
  after a new commit.
- UI: a "Rules" button on each repo row shows the head, counts of always / scoped / relevance rule sections, templates per
  doc type with their default variant, and every warning.
- Each `TemplateVariant` also keeps the whole template `text` (read when the catalog is built, so it is cached with the catalog
  and served `stale` when the host is down); `to_dict` still lists only headings.
Not yet: the combined context response (P9). The cache is in memory, so it is cold after a restart.
Open: a template's doc type is its file or folder name uppercased (`brd.md` -> `BRD`) unless `golden.yaml` `doc_types` names it
(or an alias); real template names and the `nomenclature.md` format are still to be confirmed with the team. ETag conditional
requests are not used (head-sha check + blob-sha body reuse cover it for now).

## Rule and template selection (P8, done)
`services/context/` turns explicit request fields into the rules and template to use. No free text, embedder or inference.
- `selection.py`: `select(catalog, Request(doc_type, stage, tags))`.
  - The doc type is required, matched case-insensitively against the catalog's doc types, their aliases and template types;
    unknown -> `AppError` 422 listing the known types.
  - A scope matches when every dimension it lists is satisfied (`doc_types`/`stages`: the value is in the list; `tags`: any
    overlap); a dimension the request omits does not satisfy a scope that lists it; an unlisted dimension means any.
  - Rules: `always` first, then `applies_to` matches, each ordered by priority, file, then position in the file. `matched_on` is
    `always` or `scope: <dimensions that matched>`. Untagged (`relevance`) sections are never selected; one `unscoped_rules`
    warning counts them.
  - Template: among the doc type's variants whose scope matches, the one matching the most dimensions wins (a default breaks
    ties), else the default; none gives `template: null` and a `no_template` / `no_matching_template` warning.
- `service.py`: `preview(project_id, doc_type, stage, tags)` gets the project's catalog (so it is cached by head sha and
  `stale` when the host is down) and returns `request`, `snapshot.rules_commit`, `rules[]` (`file`, `section`, `text`,
  `matched_on`, `priority`, `source_url` to the section's lines at the rules commit), `template` (`path`, `variant`, `text`,
  `sections`, `source_url`), the catalog warnings plus selection warnings, and `stale`.
- Not yet: knowledge retrieval, budgets, rerank and the Claude tools (P9); inference and relevance selection are deferred.

## Not built yet
- P6 remainder: YAML front-matter parsing (`fm.*` payload fields).
- Webhooks (instant updates; needs a public URL and per-repo setup by the customer) and hash-diff incremental ingest.
- Several app instances (needs shared scheduling and a shared database).
- Free-text inference and relevance selection of untagged rule sections (deferred from P8; revisit after P11).
- P9 (old W2): `get_context` / function-calling tool returning policies + nomenclature + template, with budgets and rerank.
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
    catalog/    manifest, sections, templates, catalog, local, live, service, models
    context/    selection (rules + template variant from doc type, stage, tags), service (preview response)
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
