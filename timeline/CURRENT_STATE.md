# Current state

_Last updated: 2026-10-28 (branch `goldan-repo-re`, phase P3 of `plan/phases.md`; P0-P2 and the chunking part of P6 done)_

## What the app does today
A FastAPI web app (src layout, managed by `uv`, Python >=3.14). The user enters a GitHub repo
URL and a PAT in a single-page UI. The backend:

1. Parses the URL (`services/sources/registry.parse_repo_url`; the host's adapter owns the URL shape) into a host-aware `RepoRef`
   (`host_kind`, `host`, `path_parts`, `name`) with a `slug` such as `github.com__acme__golden`.
   GitHub, GitHub Enterprise and Azure DevOps hosts are accepted (`config.SUPPORTED_HOST_KINDS`); GitLab and
   Bitbucket URLs get a "not supported yet" error. ADO URLs (`dev.azure.com/{org}/{project}/_git/{repo}`, legacy
   `{org}.visualstudio.com`, project-less shorthand) normalize to host `dev.azure.com`, `path_parts=(org, project)`. The slug keys the `.env` token entry, the
   clone folder, the Qdrant collection and the ingestion status, so the same owner/name on two hosts never collide.
2. Picks the host's `SourceAdapter` (`adapter_for(ref, PatCredential(token))`) and lists the repo root with
   `adapter.list_dir("")`. Adapters: GitHub/GHE and Azure DevOps (PAT as Basic with an empty user); routes, validator and ingestion never call a host directly.
3. Validates the "golden repo" structure (`services/validator.find_missing`): files
   `policies.md`, `nomenclature.md`; folders `project-data/`, `templates/` (case-sensitive,
   defined in `config.py`). Missing items -> HTTP 422 listing them.
4. Shallow-clones (`--depth 1`) into `temp_storage/<slug>/` (`services/cloner.py` picks the folder and replaces any
   earlier clone; `adapter.clone` does it via `sources/git.py`); records commit SHA + branch. The adapter supplies a
   one-off `http.extraheader` passed via `GIT_CONFIG_*` env vars (not in the URL, `.git/config` or process args).
   The token reaches adapters only as a `PatCredential` (redacted `repr`, read via `.secret()`).
   As soon as the host accepts the PAT (root listing succeeds, even if the repo then fails validation) the URL + PAT are saved to the git-ignored `.env` (`services/token_store.py`);
   a blank token field in the UI reuses the saved one. Tokens are never returned by any API. Entries saved
   before P1 (`ASTRA_REPO_<OWNER>__<NAME>_*`) are moved to the host-aware key the first time that repo is used.
5. Queues a **background ingestion** of `project-data/` (`services/ingestion/pipeline.py`):
   load (md, txt, csv, docx; others reported as skipped; symlinks, junctions and anything resolving outside
   the clone are never followed and are reported as skipped; the clone itself uses `core.symlinks=false`) -> chunk (markdown: **one chunk per heading section** with its own heading path, oversize sections split, tables/code fences kept whole, horizontal-rule lines `---` / `***` / `___` omitted from the text (decoration only, never a chunk boundary; table separator rows, code fences and setext underlines untouched);
   CSV: **one chunk per row** + a small summary chunk; <=~480 est. tokens) -> embed locally with fastembed (dense
   `BAAI/bge-base-en-v1.5`, sparse `Qdrant/bm25`) -> upsert to Qdrant collection
   `astra__<slug>` (recreated each time). Each chunk's payload has repo, repo_slug, host, commit_sha,
   path, folder_parts, heading_path / line range / row range (+ `row_key` for CSV), `doc_type` (from the folder),
   `doc_date` and `doc_meta` (parsed from email / meeting / CR / owner header lines, or the filename date), `has_open_item` /
   `open_items` ("Open: ...", "to decide"), file_hash, chunk ids, embedding
   model, ingested_at and a permalink `source_url` built by `adapter.citation_url`.

Endpoints: `POST /api/validate-and-clone` (returns the repo `slug`), `GET /api/ingestion-status/{slug}`,
`POST /api/search` (`slug` + `query`; hybrid RRF search; optional `folder`, `file_type` filters). Page at `/`,
OpenAPI at `/docs`. The UI polls ingestion status after a clone.

Qdrant runs in Docker (`docker-compose.yml`, v1.20.0, named volume). Embedding models download on
first use into `.cache/fastembed` (git-ignored).

Retrieval has **no recency or authority preference**: date and doc type are information only, search returns every hybrid
match and the LLM decides between conflicting sources.

## Not built yet
- P6 remainder: YAML front-matter parsing (`fm.*` payload fields).
- W2: function-calling tool returning policies + nomenclature + template from GitHub.
- Incremental re-ingest (currently full rebuild), pdf/xlsx loaders, reranking.

## Layout
```
src/astra_rag/  __init__ (app factory, main), config, routes
  services/     repo_ref, validator, cloner, token_store, errors
    sources/    base (SourceAdapter port), credentials (PatCredential), registry, github, azure_devops, git, http, json_reply, errors
    ingestion/  loader, md_chunker, csv_chunker, doc_meta, chunker, embedder, store, pipeline, models, tokens
  templates/ static/   UI
tests/          unittest suites + fixtures/repo (sample project-data); tests/sources/ holds the adapter contract suite
docker-compose.yml   Qdrant
temp_storage/   cloned repos (git-ignored)
timeline/       this progress record
plan/           design plans: golden-repo-rag-plan.md (requirements), phases.md (P0-P11 delivery order)
```

## Commands
- Qdrant: `docker compose up -d qdrant` (dashboard http://localhost:6333/dashboard)
- Run: `uv run python -m astra_rag` (http://127.0.0.1:5000)
- Test: `uv run python -m unittest discover -s tests -t .`
