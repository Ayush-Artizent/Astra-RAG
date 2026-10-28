# Astra RAG – Repository Connector

Simple web UI: enter a GitHub or Azure DevOps repo URL, a PAT and optionally a branch to track (blank = the repo's
default branch, or the branch saved earlier). The app checks the root of that branch for
`policies.md`, `nomenclature.md`, `project-data/` and `templates/`. If **all** exist it
clones the repo into `temp_storage/` and ingests `project-data/` into Qdrant (chunks + local embeddings, with
source metadata); otherwise it lists exactly what is missing.

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
Env overrides: `QDRANT_URL`, `QDRANT_API_KEY`, `FASTEMBED_CACHE_DIR`, `ASTRA_DB_PATH`.

Connected repos, their tracked branch, project bindings and ingestion runs are kept in SQLite at `data/astra.db`
(git-ignored; created and migrated on startup), so the repo list and last status survive a restart.

API:
- `POST /api/validate-and-clone` (`url`, `token`, optional `branch`; 409 while that repo is already ingesting)
- `GET /api/ingestion-status/{slug}`
- `GET /api/repos`, `PUT /api/repos/{slug}/settings` (`tracked_branch`; reconnect to rebuild from it)
- `PUT /api/projects/{project_id}/binding` (`repo_slug`), `GET /api/projects/{project_id}`
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
    connections.py           connect flow (token, branch, structure, register, clone) and branch changes
    registry/                SQLite store: repos, project bindings, ingestion runs, migrations
    repo_ref.py              host-aware RepoRef + slug
    sources/                 one adapter per Git host behind a SourceAdapter port (github.py, azure_devops.py), PatCredential, registry
    validator.py             required-structure check
    cloner.py                git clone into temp_storage/ (returns path, commit SHA, branch)
    ingestion/               loader, chunkers (md per section, csv per row), doc_meta (header metadata), embedder (fastembed), store (Qdrant), pipeline
    cloner.py                picks temp_storage/<slug>, replaces an old clone, asks the adapter to clone
    ingestion/               loader, chunkers (md/csv), embedder (fastembed), store (Qdrant), pipeline
    errors.py                user-safe AppError
  templates/index.html       the UI
  static/                    style.css, app.js
tests/                       unit tests + fixtures/
docker-compose.yml           Qdrant
data/                        registry database (git-ignored)
temp_storage/                cloned repos (git-ignored)
```

## Security notes
- **The API has no authentication yet.** Anyone who can reach the server can connect repos, change branches and bind
  projects. Keep it on `127.0.0.1` (the default) or behind a trusted proxy until API auth is added.
- Once the host accepts a typed PAT (the root listing succeeds, even if the repo then fails the structure check) the
  cleaned repo URL and PAT are saved in `.env` (git-ignored, key `ASTRA_REPO_<HOST>__<OWNER>__<NAME>_TOKEN`) so later
  steps can reuse them; leave the token field blank to use the saved one. Treat `.env` as a secret. The registry
  database stores only the name of that key, never the token.
- The token is passed to git as a one-off header through environment variables (not in the URL,
  `.git/config` or process arguments) and is never returned by the API.
- A repeat clone of the same repo replaces the previous copy. Until phase P5, a re-ingest also drops the Qdrant
  collection before rebuilding it, so search is empty during a rebuild (and partial if it fails).
