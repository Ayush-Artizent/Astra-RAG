# Current state

_Last updated: 2026-10-27 (branch `golden-repo-init`)_

## What the app does today
A FastAPI web app (src layout, managed by `uv`, Python >=3.14). The user enters a GitHub repo
URL and a PAT in a single-page UI. The backend:

1. Parses the URL (`services/github_client.parse_repo_url`).
2. Lists the repo root via the GitHub API (`github_client.list_root`).
3. Validates the "golden repo" structure (`services/validator.find_missing`): files
   `policies.md`, `nomenclature.md`; folders `project-data/`, `templates/` (case-sensitive,
   defined in `config.py`).
4. If anything is missing -> HTTP 422 listing exactly what is missing.
5. Otherwise shallow-clones (`--depth 1`) into `temp_storage/<owner>__<name>/`
   (`services/cloner.py`), replacing any earlier clone. Token is passed as a one-off
   `http.extraheader`, never stored on disk.

Single endpoint: `POST /api/validate-and-clone`. Page at `/`, OpenAPI docs at `/docs`.

## Not built yet
- RAG ingestion (chunking, embeddings, vector store) - nothing happens after the clone.
- Function-calling tool that fetches `policies.md` + a document template.
- No LLM client, no embedding model, no vector DB dependency in `pyproject.toml`.

## Layout
```
src/astra_rag/  __init__ (app factory, main), config, routes
  services/     github_client, validator, cloner, errors
  templates/ static/   UI
tests/          test_validator_and_url.py (unit tests, unittest)
temp_storage/   cloned repos (git-ignored)
timeline/       this progress record
```

## Commands
- Run: `uv run python -m astra_rag` (http://127.0.0.1:5000)
- Test: `uv run python -m unittest discover -s tests -t .`
