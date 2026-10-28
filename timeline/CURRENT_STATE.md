# Current state

_Last updated: 2026-10-28 (branch `goldan-repo-re`, phase P1 of `plan/phases.md`)_

## What the app does today
A FastAPI web app (src layout, managed by `uv`, Python >=3.14). The user enters a GitHub repo
URL and a PAT in a single-page UI. The backend:

1. Parses the URL (`services/repo_ref.parse_repo_url`) into a host-aware `RepoRef`
   (`host_kind`, `host`, `path_parts`, `name`) with a `slug` such as `github.com__acme__golden`.
   Only GitHub and GitHub Enterprise hosts are accepted (`config.SUPPORTED_HOST_KINDS`); Azure DevOps,
   GitLab and Bitbucket URLs get a "not supported yet" error. The slug keys the `.env` token entry, the
   clone folder, the Qdrant collection and the ingestion status, so the same owner/name on two hosts never collide.
2. Lists the repo root via the GitHub API (`github_client.list_root`).
3. Validates the "golden repo" structure (`services/validator.find_missing`): files
   `policies.md`, `nomenclature.md`; folders `project-data/`, `templates/` (case-sensitive,
   defined in `config.py`). Missing items -> HTTP 422 listing them.
4. Shallow-clones (`--depth 1`) into `temp_storage/<slug>/` (`services/cloner.py`),
   replacing any earlier clone; records commit SHA + branch. The token goes to git as a one-off
   `http.extraheader` via `GIT_CONFIG_*` env vars (not in the URL, `.git/config` or process args).
   After a successful clone the URL + PAT are saved to the git-ignored `.env` (`services/token_store.py`);
   a blank token field in the UI reuses the saved one. Tokens are never returned by any API. Entries saved
   before P1 (`ASTRA_REPO_<OWNER>__<NAME>_*`) are moved to the host-aware key the first time that repo is used.
5. Queues a **background ingestion** of `project-data/` (`services/ingestion/pipeline.py`):
   load (md, txt, csv, docx; others reported as skipped; symlinks, junctions and anything resolving outside
   the clone are never followed and are reported as skipped; the clone itself uses `core.symlinks=false`) -> chunk (markdown by heading, CSV by
   row groups + summary chunk, <=~480 est. tokens) -> embed locally with fastembed (dense
   `BAAI/bge-base-en-v1.5`, sparse `Qdrant/bm25`) -> upsert to Qdrant collection
   `astra__<slug>` (recreated each time). Each chunk's payload has repo, repo_slug, host, commit_sha,
   path, folder_parts, heading_path / line range / row range, file_hash, chunk ids, embedding
   model, ingested_at and a GitHub permalink `source_url`.

Endpoints: `POST /api/validate-and-clone` (returns the repo `slug`), `GET /api/ingestion-status/{slug}`,
`POST /api/search` (`slug` + `query`; hybrid RRF search; optional `folder`, `file_type` filters). Page at `/`,
OpenAPI at `/docs`. The UI polls ingestion status after a clone.

Qdrant runs in Docker (`docker-compose.yml`, v1.20.0, named volume). Embedding models download on
first use into `.cache/fastembed` (git-ignored).

## Not built yet
- W2: function-calling tool returning policies + nomenclature + template from GitHub.
- Incremental re-ingest (currently full rebuild), pdf/xlsx loaders, reranking.

## Layout
```
src/astra_rag/  __init__ (app factory, main), config, routes
  services/     repo_ref, github_client, validator, cloner, token_store, errors
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
