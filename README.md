# Astra RAG – Repository Connector

Simple web UI: enter a GitHub repo URL and a PAT. The app checks the repo root for
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
Env overrides (env or `.env`, see `.env.example`): `QDRANT_URL`, `QDRANT_API_KEY`, `FASTEMBED_CACHE_DIR`.

API: `POST /api/validate-and-clone`, `GET /api/ingestion-status/{owner}/{name}`, `POST /api/search`,
`GET /api/tools[?owner=&name=]` (tool schema), `POST /api/tools/invoke`.

**LLM tool `get_document_context`** (W2): connect a repo first (that saves its URL + PAT in `.env`). Then
`POST /api/tools/invoke` with `{"name": "get_document_context", "arguments": {"owner": "acme", "name": "golden", "request_type": "BRD"}}`
returns `policies.md`, `nomenclature.md` and `templates/brd.md` read live from GitHub (not the clone, not RAG), plus their blob SHAs.
A template is any `.md` file in `templates/`; its request type is the filename stem uppercased. No auth on the endpoint yet.

## Structure

```
pyproject.toml               deps, deps and `astra-rag` script (uv)
src/astra_rag/
  __init__.py                FastAPI app factory + main()
  config.py                  required files/folders, paths, timeouts, Settings (env)  <- edit rules here
  routes.py                  page + POST /api/validate-and-clone
  services/
    github_client.py         URL parsing, GitHub API list_dir / get_file
    validator.py             required-structure check
    cloner.py                git clone into temp_storage/ (returns path, commit SHA, branch)
    ingestion/               loader, chunkers (md/csv), embedder (fastembed), store (Qdrant), pipeline
    tools/                   W2: one directory per LLM tool + base.py (Tool, RepoArgs, Claude/MCP renderers) + registry.py (TOOLS table, dispatcher)
      document_context/      schemas.py (args + result), handler.py (policies + template from GitHub), __init__.py exports `tool`
    token_store.py           saved URL + PAT per repo in .env (ASTRA_REPO_<OWNER>__<NAME>_*)
    errors.py                user-safe AppError
  templates/index.html       the UI
  static/                    style.css, app.js
tests/                       unit tests + fixtures/
docker-compose.yml           Qdrant
temp_storage/                cloned repos (git-ignored)
```

## Security notes
- After a successful connect the repo URL and PAT are saved in `.env` (git-ignored, key `ASTRA_REPO_<OWNER>__<NAME>_TOKEN`)
  so later steps can reuse them; leave the token field blank to use the saved one. Treat `.env` as a secret.
- The token is passed to git as a one-off header through environment variables (not in the URL,
  `.git/config` or process arguments) and is never returned by the API.
- A repeat clone of the same repo replaces the previous copy.
