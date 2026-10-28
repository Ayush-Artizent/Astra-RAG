# Current state

_Last updated: 2026-10-27 (branch `golden-repo-init`)_

## What the app does today
A FastAPI web app (src layout, managed by `uv`, Python >=3.14). The user enters a GitHub repo
URL and a PAT in a single-page UI. The backend:

1. Parses the URL (`services/github_client.parse_repo_url`).
2. Lists the repo root via the GitHub API (`github_client.list_root`).
3. Validates the "golden repo" structure (`services/validator.find_missing`): files
   `policies.md`, `nomenclature.md`; folders `project-data/`, `templates/` (case-sensitive,
   defined in `config.py`). Missing items -> HTTP 422 listing them.
4. Shallow-clones (`--depth 1`) into `temp_storage/<owner>__<name>/` (`services/cloner.py`),
   replacing any earlier clone; records commit SHA + branch. The token goes to git as a one-off
   `http.extraheader` via `GIT_CONFIG_*` env vars (not in the URL, `.git/config` or process args).
   After a successful clone the URL + PAT are saved to the git-ignored `.env` (`services/token_store.py`);
   a blank token field in the UI reuses the saved one. Tokens are never returned by any API.
5. Queues a **background ingestion** of `project-data/` (`services/ingestion/pipeline.py`):
   load (md, txt, csv, docx; others reported as skipped) -> chunk (markdown by heading, CSV by
   row groups + summary chunk, <=~480 est. tokens) -> embed locally with fastembed (dense
   `BAAI/bge-base-en-v1.5`, sparse `Qdrant/bm25`) -> upsert to Qdrant collection
   `astra__<owner>__<name>` (recreated each time). Each chunk's payload has repo, commit_sha,
   path, folder_parts, heading_path / line range / row range, file_hash, chunk ids, embedding
   model, ingested_at and a GitHub permalink `source_url`.

Endpoints: `POST /api/validate-and-clone`, `GET /api/ingestion-status/{owner}/{name}`,
`POST /api/search` (hybrid RRF search; optional `folder`, `file_type` filters). Page at `/`,
OpenAPI at `/docs`. The UI polls ingestion status after a clone.

Qdrant runs in Docker (`docker-compose.yml`, v1.20.0, named volume). Embedding models download on
first use into `.cache/fastembed` (git-ignored).

## Not built yet
- W2: function-calling tool returning policies + nomenclature + template from GitHub.
- Incremental re-ingest (currently full rebuild), pdf/xlsx loaders, reranking.

## Layout
```
src/astra_rag/  __init__ (app factory, main), config, routes
  services/     github_client, validator, cloner, errors
    ingestion/  loader, md_chunker, csv_chunker, chunker, embedder, store, pipeline, models, tokens
  templates/ static/   UI
tests/          unittest suites + fixtures/repo (sample project-data)
docker-compose.yml   Qdrant
temp_storage/   cloned repos (git-ignored)
timeline/       this progress record
plan/           design plans: golden-repo-rag-plan.md (requirements), phases.md (P0-P11 delivery order)
```

## Commands
- Qdrant: `docker compose up -d qdrant` (dashboard http://localhost:6333/dashboard)
- Run: `uv run python -m astra_rag` (http://127.0.0.1:5000)
- Test: `uv run python -m unittest discover -s tests -t .`
