# Astra RAG – Repository Connector

Simple web UI: enter a GitHub repo URL and a PAT. The app checks the repo root for
`policies.md`, `nomenclature.md`, `project-data/` and `templates/`. If **all** exist it
clones the repo into `temp_storage/`; otherwise it lists exactly what is missing.

## Run

Requires [uv](https://docs.astral.sh/uv/) and `git` on PATH. The PAT needs read access to repo contents.

```bash
uv sync
uv run astra-rag        # http://127.0.0.1:5000  (API docs at /docs)
```

Tests: `uv run python -m unittest discover -s tests -t .`

## Structure

```
pyproject.toml               deps, `astra-rag` command (uv)
src/astra_rag/
  __init__.py                FastAPI app factory + main()
  config.py                  required files/folders, paths, timeouts  <- edit rules here
  routes.py                  page + POST /api/validate-and-clone
  services/
    github_client.py         URL parsing, GitHub API root listing
    validator.py             required-structure check
    cloner.py                git clone into temp_storage/
    errors.py                user-safe AppError
  templates/index.html       the UI
  static/                    style.css, app.js
tests/                       unit tests
temp_storage/                cloned repos (git-ignored)
```

## Security notes
- The token is used per request, never stored, and passed to git as a one-off header
  (not embedded in the URL or `.git/config`).
- A repeat clone of the same repo replaces the previous copy.
