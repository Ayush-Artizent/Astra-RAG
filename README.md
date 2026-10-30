# Astra RAG – Repository Connector

Simple web UI: enter a GitHub or Azure DevOps repo URL, a PAT and optionally a branch to track (blank = the repo's
default branch, or the branch saved earlier). The app checks the root of that branch for
`policies.md`, `nomenclature.md`, `project-data/` and `templates/`. If **all** exist it
registers the repo and starts a background sync: clone into `temp_storage/`, then ingest `project-data/` into Qdrant
(chunks + local embeddings, with source metadata); otherwise it lists exactly what is missing.

## Rules and templates (golden catalog)
Besides `project-data/`, the repo's rules and templates are read **live from the host** (not indexed). The **Rules**
button on a repo row (or `GET /api/repos/{slug}/catalog`, `GET /api/projects/{project_id}/catalog`) shows what the
app found on the tracked branch: rule sections from `policies.md`, `nomenclature.md` and `rules/**.md` (one per heading),
templates from `templates/<type>.md` or `templates/<type>/<variant>.md`, and warnings.
An optional `golden.yaml` at the repo root marks sections `always: true` or `applies_to: {doc_types, stages, tags}`, names
the default template variant, and lists doc-type aliases, stages and tags. A missing or broken `golden.yaml` is only a
warning; without it nothing is guaranteed to apply (the page warns "no always-on rules defined").

`POST /api/context/preview` picks the rules and template for a request: send `project_id`, `doc_type` and optionally
`stage` and `tags`. It returns the `always` rules, then the rules whose `applies_to` matches (every dimension a rule lists
must match), and the best-matching template variant with its **whole text**. Sections that have no scope are never selected;
the response warns how many, so mark them `always: true` or give them `applies_to`.

## Keeping the index fresh (sync)
Nothing to set up on the repository side: the server uses the PAT it already has.
- **Nightly:** every night at `ASTRA_SYNC_DAILY_AT` (default `02:00`, **UTC**) the server checks each repo's tracked
  branch head and rebuilds only if it moved (or the branch setting changed). A server that was down at that time
  catches up at its next start. **So a change can take up to a day to appear in search.**
- **Sync now:** the button on each repo row (or `POST /api/repos/{slug}/sync`) checks right away and queues a rebuild
  if needed. A trigger that arrives while a sync is running is folded into one follow-up run.
- A rebuild writes a new Qdrant collection version and then switches the repo's alias to it in one step, so search
  keeps serving the previous index during a rebuild and after a failed one.
- The repos table shows each repo's indexed commit and when it was indexed, when it was last checked, its sync
  status (`up to date`, `syncing`, `queued`, `rebuild pending`, `cannot reach the repository`, ...) and the next
  scheduled check.
- **Expired or revoked PAT:** the repo shows "cannot reach the repository" with the host's message, and the old
  index keeps serving. Fix it by connecting the same URL again with a new PAT (branch field blank); that replaces
  the saved token and clears the error.

## Run

Requires [uv](https://docs.astral.sh/uv/) and `git` on PATH. The PAT needs read access to repo contents.

```bash
docker compose up -d qdrant   # vector DB (Rancher Desktop / Docker); dashboard at :6333/dashboard
uv sync
uv run python -m astra_rag   # http://127.0.0.1:5000  (API docs at /docs)
```

`uv run astra-rag` also works, but some Windows setups block the generated `.exe`
("Access is denied"); use the `python -m` form above in that case.

Tests: `uv run python -m unittest discover -s tests -t .`

The first ingestion downloads the embedding models (~200 MB) into `.cache/fastembed`.
Env overrides: `QDRANT_URL`, `QDRANT_API_KEY`, `FASTEMBED_CACHE_DIR`, `ASTRA_DB_PATH`, `ASTRA_SYNC_DAILY_AT`
(`HH:MM`, UTC), `ASTRA_SYNC_SCHEDULER=0` (turns off the nightly check, the startup catch-up and the startup index
recovery; for tests and maintenance only).

Connected repos, their tracked branch, project bindings and ingestion runs are kept in SQLite at `data/astra.db`
(git-ignored; created and migrated on startup), so the repo list and last status survive a restart.

**Run exactly one instance per data directory.** The scheduler, the sync worker and the startup recovery run inside
the app process, and the database is SQLite. The app takes an exclusive lock on `data/astra.lock` at startup and a
second instance on the same data directory refuses to start. Do not run uvicorn with `--workers` > 1. Several
replicas would need shared scheduling and a shared database (not built).

API:
- `POST /api/validate-and-clone` (`url`, `token`, optional `branch`; queues a sync and returns `ingestion.state`
  `queued`, or `pending` if one is already running)
- `GET /api/ingestion-status/{slug}`
- `GET /api/repos` (with sync status and the nightly `schedule`), `POST /api/repos/{slug}/sync` (Sync now:
  `up_to_date` / `queued` / `pending`), `PUT /api/repos/{slug}/settings` (`tracked_branch`; starts a rebuild from it)
- `PUT /api/projects/{project_id}/binding` (`repo_slug`), `GET /api/projects/{project_id}`
- `GET /api/projects/{project_id}/catalog`, `GET /api/repos/{slug}/catalog` (rules and templates read live from the tracked branch, with warnings; `?include_text=true` adds rule text)
- `POST /api/context/preview` (body: `project_id`, `doc_type`, optional `stage`, `tags`; the selected rules and the whole template)
- `POST /api/search` (body has `slug`)

A repo's `slug` is host-aware, e.g. `github.com__acme__golden`; the clone response returns it.

## Structure

```
pyproject.toml               deps, deps and `astra-rag` script (uv)
src/astra_rag/
  __init__.py                FastAPI app factory + main()
  config.py                  required files/folders, paths, timeouts  <- edit rules here
  routes.py                  thin HTTP layer: page + the API endpoints above
  services/
    connections.py           connect flow (token, branch, structure, register, queue a sync) and branch changes
    registry/                SQLite store: repos, project bindings, ingestion runs, migrations
    sync/                    sync service (check head, queue, clone, ingest, follow-up), worker, nightly scheduler,
                             startup index recovery, single-instance lock
    repo_ref.py              host-aware RepoRef + slug
    sources/                 one adapter per Git host behind a SourceAdapter port (github.py, azure_devops.py), PatCredential, registry
    validator.py             required-structure check
    cloner.py                git clone into temp_storage/ (returns path, commit SHA, branch)
    ingestion/               loader, chunkers (md per section, csv per row), doc_meta (header metadata), embedder (fastembed), store (Qdrant), pipeline
    cloner.py                picks temp_storage/<slug>, replaces an old clone, asks the adapter to clone
    ingestion/               loader, chunkers (md/csv), embedder (fastembed), store (Qdrant versions + alias), pipeline
    catalog/                 golden catalog: golden.yaml manifest, rule sections, templates, warnings (live reads of rules and templates)
    context/                 picks the rules and template variant for a doc type, stage and tags (preview endpoint)
    errors.py                user-safe AppError
  templates/index.html       the UI
  static/                    style.css, app.js
tests/                       unit tests + fixtures/
docker-compose.yml           Qdrant
data/                        registry database + instance lock (git-ignored)
temp_storage/                cloned repos (git-ignored)
```

## Security notes
- **The API has no authentication yet.** Anyone who can reach the server can connect repos, change branches, bind
  projects and start syncs (host calls and CPU-heavy embedding). Keep it on `127.0.0.1` (the default) or behind a
  reverse proxy that authenticates users. **Never expose it directly to the internet.**
- Once the host accepts a typed PAT (the root listing succeeds, even if the repo then fails the structure check) the
  cleaned repo URL and PAT are saved in `.env` (git-ignored, key `ASTRA_REPO_<HOST>__<OWNER>__<NAME>_TOKEN`) so later
  steps can reuse them; leave the token field blank to use the saved one. Treat `.env` as a secret: it is written
  with mode 600 where the OS supports it; on Windows restrict it to the account that runs the server, e.g.
  `icacls .env /inheritance:r /grant:r "%USERNAME%:F"`. The registry database stores only the name of that key,
  never the token. Sync errors, run errors and logs carry only safe messages (never the token or the host's reply).
- The token is passed to git as a one-off header through environment variables (not in the URL,
  `.git/config` or process arguments) and is never returned by the API.
- A repeat clone of the same repo replaces the previous copy. The Qdrant index is replaced only once the new
  version is complete (alias switch), so search is never empty during a rebuild.
