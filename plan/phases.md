# Golden Repo RAG: delivery phases

> **Status: draft for team discussion (2026-10-28).**
> **Based on:** [golden-repo-rag-plan.md](golden-repo-rag-plan.md). Section references such as §A and §D3 point to that file.

## How we work through the phases
- **One phase at a time.** Each phase gets its own branch and PR. Do not start the next phase until the current one is merged.
- **Small and shippable.** Every phase leaves the app working end to end. The connect, clone, ingest and search flow that works today must keep working.
- **Behaviour first, then refactor, never both at once.** A phase that moves code (for example P2) changes no behaviour. A phase that adds behaviour builds on code that has already been moved.
- **Definition of done for every phase:**
  - All tests pass: `uv run python -m unittest discover -s tests -t .`
  - New logic has tests, and the tests need no network and no real tokens.
  - The phase's acceptance checks below have been run by hand.
  - `timeline/CURRENT_STATE.md`, `TASKS.md` and `CHANGELOG.md` are updated, and `README.md` too if run steps changed.
  - Anything we learned that changes later phases is written back into this file.
- **Scope guard.** If a phase starts needing work from a later phase, stop and discuss. Do not pull the work forward quietly.

## Overview

| Phase | Name | Size | Depends on | Delivers |
|---|---|---|---|---|
| P0 | Safety fixes and doc cleanup | S | none | Symlink-safe loader, correct docs |
| P1 | Host-aware repo identity | S | P0 | `RepoRef` + keys that can't collide across hosts |
| P2 | Source adapter port + GitHub adapter | M | P1 | `services/sources/` with GitHub behind it, no behaviour change |
| P3 | Azure DevOps adapter | M | P2 | Connect, validate, clone and ingest an ADO golden repo |
| P4 | Repo registry, bindings and tracked branch | M | P3 | Persistent repos, project→repo binding, branch config, persistent status |
| P5 | Sync: nightly + Sync now, alias swap | M | P4 | Index follows the tracked branch with no empty-index window |
| P6 | Structure- and metadata-aware ingestion | S | P0 | Per-section and per-row chunks, header metadata, open items (done); front-matter in payload (todo) |
| P7 | Golden catalog (`golden.yaml`, rule sections, templates) | L | P4 | Live catalog of rules and templates, plus warnings |
| P8 | Rule selection and request inference | M | P7 | always / scope / relevance selection, doc type, stage and tag inference |
| P9 | `get_context` API, sub-queries, rerank, tools | L | P5, P6, P8 | The combined context response and Claude tool schemas |
| P10 | GitLab and Bitbucket adapters | M | P2 (any time after) | Two more hosts |
| P11 | Evaluation set and tuning | M | P9 | Measured defaults for thresholds and budgets |

Size key: S is about 1-2 days, M about 3-5 days, L about 1-2 weeks. These are rough guides, not commitments.
P6 depends only on P0, so it can be done early if someone is free. P10 can run in parallel with P5-P9.

---

## P0: Safety fixes and doc cleanup
**Goal:** close the known security gap before anything else, and make the docs match reality.

**Scope**
- `services/ingestion/loader.py`:
  - skip symlinks (`path.is_symlink()`);
  - skip any file whose `resolve()` lands outside the clone;
  - report each one as skipped with a reason.
- `cloner.py`: clone with `core.symlinks=false` (through the existing `GIT_CONFIG_*` env vars) as a second layer.
- Docs:
  - correct the branch name in `CURRENT_STATE.md` and `CLAUDE.md` (`goldan-repo`);
  - add `token_store.py` to the layout;
  - fix TASKS W2.5 "token never persisted", which now contradicts the `.env` storage.

**Out of scope:** anything host- or adapter-related.

**Tests**
- A fixture with a symlink to a file outside the repo is skipped, not indexed.
- Skip the test cleanly on Windows if symlinks can't be created.

**Acceptance**
- On Linux/macOS, a repo containing `project-data/x.md -> ../../../.env` does not appear in search.

---

## P1: Host-aware repo identity
**Goal:** make repo identity correct for several hosts before any adapter exists (§D, code gaps).

**Scope**
- `RepoRef` becomes `{host_kind, host, path_parts, name}`:
  - `host_kind` is `github | ghe | azure_devops | gitlab | bitbucket`;
  - it gets a stable `slug` that includes the host.
- Only GitHub URLs are accepted in this phase. Other hosts give a clear "not supported yet" error.
- Use the host-aware slug in:
  - `token_store._key`
  - `store.collection_name`
  - the clone folder name
  - the pipeline status key
- One-off migration: read old `ASTRA_REPO_<OWNER>__<NAME>_*` keys from `.env` once and rewrite them under the new key.
  Existing Qdrant collections are simply rebuilt on the next connect.

**Out of scope:** ADO URL parsing (P3).

**Tests**
- The same owner/name on two hosts gives different slugs.
- The old `.env` key is migrated.
- Existing URL tests still pass.

**Acceptance**
- Connect, ingest and search for a GitHub repo work as before.

---

## P2: Source adapter port + GitHub adapter (refactor only)
**Goal:** create the reusable `services/sources/` package (§D3) and move GitHub behind it. **No behaviour change.**

**Scope**
- `services/sources/base.py`:
  - `SourceAdapter` protocol:
    - `parse_url`
    - `list_dir(path, ref)`
    - `read_file(path, ref)`
    - `head_sha(branch)`
    - `default_branch()`
    - `clone(dest, branch)`
    - `citation_url(path, sha, lines)`
    - `is_ancestor(base, head)`
    - a `verify_webhook` stub for later
  - a `Credential` protocol (PAT only for now);
  - shared error mapping to `AppError`.
- `services/sources/registry.py`: picks the adapter from the URL host.
  - P1 note: `RepoRef`, `host_kind()` and `parse_repo_url` live in `services/repo_ref.py`. GitHub-only bits still on `RepoRef` (`clone_url`, `api_base`) move into the GitHub adapter here; `parse_repo_url` becomes the registry's dispatch.
- `services/sources/github.py`: the existing `github_client` and `cloner` logic, moved here.
- `routes.py`, `validator` and ingestion call the adapter, not `github_client` or `cloner` directly.
  - `chunker._source_url` uses `adapter.citation_url`.
- `tests/sources/contract.py`: a shared contract test mixin every adapter must pass, using faked HTTP (`fake_http.py`) and a local bare git repo.
  A host's test class supplies `make_adapter` and `stub_*` hooks that script that host's REST replies (see `test_github.py`).
  - P2 done: `PatCredential`, `base.py` (ABC, not Protocol, so `verify_webhook` has a default), `git.py` (shared clone; adapters supply only the auth header), `http.py`, `errors.py`.
  - P2 done: `parse_repo_url` now lives in `sources/registry.py`; `repo_ref.py` keeps only `RepoRef` and `host_kind`.
  - P3 hint: add the new kind to both `config.SUPPORTED_HOST_KINDS` and `registry.ADAPTERS` (a test checks they match).

**Out of scope:** new hosts, ETag caching (P7).

**Tests**
- The GitHub adapter passes the contract suite.
- The route tests keep their assertions. Only their patch targets change (`routes.adapter_for` instead of `routes.github_client.list_root`).

**Acceptance**
- Same behaviour as before, and a diff review confirms no route or response changes.

---

## P3: Azure DevOps adapter
**Goal:** the first new host (§D2), so ADO golden repos work end to end.

**Scope**
- `services/sources/azure_devops.py`:
  - **URLs:** `https://dev.azure.com/{org}/{project}/_git/{repo}` and the legacy `https://{org}.visualstudio.com/{project}/_git/{repo}`.
  - **REST:**
    - repository info, which includes `defaultBranch`;
    - `items` with `recursionLevel=OneLevel` to list a folder;
    - `items?path=&versionDescriptor` to read a file;
    - `refs?filter=heads/` to get the branch head.
  - **Auth:** PAT as Basic with an empty user, for both the REST calls and the git `http.extraheader`.
  - **Citation URL:** `?path=&version=GC{sha}&line=&lineEnd=`.
- Confirm whether ADO treats the required root names case-sensitively, and enforce exact case in our own validator either way.
- UI: the placeholder and help text mention ADO URLs.

**Out of scope:** ADO service hooks (webhooks).

**Tests**
- The contract suite passes with recorded and faked ADO responses.
- URL parsing covers both forms.
- Errors are mapped for 401, 403, 404 and "repo not found".

**Acceptance**
- Connect a real ADO golden repo, see validation, clone and ingestion succeed, and confirm search results link back to ADO at the right commit.

---

## P4: Repo registry, project bindings and tracked branch
**Goal:** move repo state out of memory and the `.env` file and into a proper store, and make the tracked branch configurable (§D1, §D6).

**Scope**
- `services/registry/`: a SQLite store (`data/astra.db`, git-ignored) with these tables:
  - `repos` (slug, url, host_kind, tracked_branch, created_at)
  - `project_bindings` (project_id → repo slug; one repo per project)
  - `ingestion_runs` (the persisted form of today's in-memory status)
- Tokens stay in `token_store` (`.env`) for now. The registry stores only a credential reference.
- The tracked branch defaults to the host's default branch, can be set at connect time and changed later. A change marks the repo for a full rebuild.
- The adapter `clone` uses `--branch <tracked> --single-branch`.
- APIs:
  - `GET /api/repos`
  - `PUT /api/repos/{slug}/settings` (tracked branch)
  - `PUT /api/projects/{project_id}/binding`
  - `GET /api/projects/{project_id}`
- `GET /api/ingestion-status` reads from the store, so it survives a restart.
- UI: a branch field on connect, and a simple repos list showing branch, last commit and state.

**Out of scope:** scheduled sync (P5), API authentication (later).

**Tests**
- Store CRUD on a temporary database.
- Binding rules: one repo per project, and a repo can serve many projects.
- Clone uses the tracked branch (checked with a local bare repo that has two branches).

**Acceptance**
- Restart the app and the repo list and last status are still there. Change the branch and the next ingest uses it.

**Learned in P4 (feeds P5)**
- `repos` keeps the configured branch (`tracked_branch` + `config_version`) apart from the last good build
  (`indexed_run_id/branch/commit_sha/collection/config_version/at`). Only a `done` run newer than the indexed one writes
  `indexed_*`; `needs_rebuild` is derived from `config_version`, not a stored flag. P5's `sync_repo` should use the same
  rule (write `indexed_*` when the alias swaps) and treat `needs_rebuild` as "rebuild even if `head_sha` is unchanged".
- P4 refuses a second connect for a repo with an active run (409, checked and queued in one `BEGIN IMMEDIATE`
  transaction). P5's per-repo lock with a coalesced follow-up run replaces this guard.
- Runs carry `index_replaced`, and `index_state` reports `incomplete` when a failed run had already dropped the
  collection. The alias swap should make that state impossible; keep the field for runs from before P5.
- The connect flow now lives in `services/connections.py`; Sync now should reuse its branch and token handling.

---

## P5: Sync: nightly and Sync now, with alias swap
**Goal:** keep the index on the latest commit of the tracked branch, with no window where search is empty (§D7, §E2).

**Scope**
- Versioned collections `<slug>__v<n>` behind an alias `<slug>`.
  - A rebuild writes into a new version, checks the point count, swaps the alias, then drops the old version.
  - This replaces `store.recreate` dropping the live collection first.
- `services/sync/`:
  - `sync_repo(slug)`: check `head_sha`, skip if unchanged, otherwise fetch or clone the new commit, run a full ingest into a new version, then swap.
  - A per-repo lock. A trigger that arrives while a sync is running is coalesced into one follow-up run.
  - A nightly scheduler in the app lifespan, at a time set by `SYNC_DAILY_AT` in `config.py`.
- `POST /api/repos/{slug}/sync` and a Sync now button. The status shows last synced commit, time and state.
- Failure handling:
  - the old version keeps serving;
  - the error is recorded;
  - a revoked token sets a `source_error` state.

**Out of scope:** webhooks, hash-diff incremental ingest (later items).

**Tests**
- An unchanged head means no ingest runs.
- A changed head gives a new version and the alias swaps.
- Search works throughout a rebuild (in-memory Qdrant).
- Concurrent triggers coalesce.
- A failed sync keeps the old index.

**Acceptance**
- Push to the tracked branch, click Sync now, and search shows the new text with the new commit SHA in `source_url`.

**Learned in P5 (feeds later phases)**
- Version collections are named `astra_v<run id>__<slug>` (not `<slug>__v<n>`): a repo whose own name ends in `__v3`
  could otherwise be mistaken for another repo's version. The alias keeps the old collection name, so `search` and any
  later reader (P9) just use `collection_name(slug)`.
- Connect now goes through the background sync (one clone/ingest path for every trigger). `register_and_queue` is the
  only place besides `set_tracked_branch` that may bump `config_version`; `queue_run` never does.
- The run row is the per-repo lock; triggers during a run set `repos.sync_pending/sync_force` and the worker starts one
  follow-up when the run ends. P4's 409 is gone.
- Single instance is enforced by an OS lock on `<data dir>/astra.lock`. Moving to several replicas (or Postgres) needs
  shared scheduling, distributed run ownership and a different recovery story.
- Webhooks still fit later: `request_sync(slug, "webhook")` is the call a verified webhook would make.

---

## P6: Structure- and metadata-aware ingestion
**Goal:** make the chunks match how project-data is really written (§E1). A review of the two example repos
(`ecommerce`, `patient appointment`) showed that sections were merged under the wrong heading, email / meeting / CR
header lines were plain body text, and CSV rows were grouped. Can start any time after P0.

**Decisions (2026-10-28, agreed with the user)**
- **One chunk per heading section**, each with its own correct heading path. A section over the size cap is split, and every
  piece keeps the section's path. A heading with no body makes no chunk (its children carry it in their path). Text before
  the first heading (e.g. an email) is its own chunk.
- **Header metadata is parsed into the payload**: `doc_type` (from the folder, mapping in `config.DOC_TYPE_BY_FOLDER`),
  `doc_date`, `doc_meta` (from / to / subject, attendees, owner, status ...). The same facts are prefixed to the embedded text.
- **One chunk per CSV row**, with `row_key` (the id-like column) and `row_start` = `row_end` = row number. One small summary
  chunk (file name, columns, row count) stays.
- **Open items** ("Open: ...", "to decide", TBD) are flagged per chunk: `has_open_item`, `open_items`.
- **No recency or authority preference.** Date and doc type are information for the LLM only. Retrieval stays plain hybrid
  RRF and returns every match; when sources disagree (e.g. COD limit 10,000 vs 7,500) the LLM sees each source's date, type
  and `source_url` and decides. No date filter, sort or boost is added.
- **Horizontal rules are omitted (decided 2026-10-28).** A line of only `---`, `***` or `___` is decoration (common in
  AI-generated Markdown). It is dropped from the chunk text **and** the embedded text. It is **not** a chunk boundary: chunks
  are still cut only by headings and size, so a rule between two paragraphs of one section just disappears and the section
  stays one chunk. A section left with only a heading or rules makes no chunk. Line numbers still count the original file, so
  permalinks stay right. Left untouched because they are not decoration:
  - table separator rows (`|---|---|`);
  - `---` inside code fences;
  - a setext heading underline (`Title` directly over `---`).

**Done (2026-10-28):** the five decisions above (`md_chunker`, `csv_chunker`, new `doc_meta.py`, `chunker` payload; tests).
Note: a CSV now costs one vector per row, bounded by `CSV_MAX_ROWS`; add a size threshold if a very large CSV shows up.



**Out of scope:** front-matter filters in the search API (P9 or later); any ranking by date or doc type.

**Tests**
- Done: section paths, heading-only sections, oversize sections, per-row CSV, header metadata (email, meeting, italic owner
  line, filename date), open items, plain prose with a colon is not metadata; rules omitted without splitting a chunk, line
  numbers unchanged, rule-only section makes no chunk, table separators / code fences / setext underlines untouched.
- Todo: front-matter is stripped; fields appear in the payload; line numbers still match the original file; bad YAML warns
  and ingestion continues.

**Acceptance**
- Done: ingest the example repos. `Not in scope` items no longer sit under `Scope`; emails and meeting notes show `doc_type`,
  `doc_date` and `doc_meta`; `RSK-001` is its own chunk with `row_key`; no chunk or embedded text contains a bare
  `---` / `***` / `___` line, while table separator rows are intact.
- Todo: ingest a repo with front-matter files. Chunks show `fm.*` fields, and no chunk text starts with `---`.

---

## P7: Golden catalog (`golden.yaml`, rule sections, templates)
**Goal:** a live, cached catalog of the repo's rules and templates (§A, §B1-2, §D5). Nothing is selected yet.

**Scope**
- `services/catalog/manifest.py`: parse `golden.yaml` v1:
  - `rules` (file, section, always / applies_to, priority)
  - `templates` (type, variant, applies_to, default)
  - `doc_types` and aliases
  - `stages`
  - `tags` vocabulary
  - `project_data` hints
  - Follow warn-and-keep-going: every problem becomes a warning, never an error.
- `services/catalog/sections.py`: split `policies.md`, `nomenclature.md` and `rules/**.md` into heading sections with stable ids.
- `services/catalog/templates.py`: discover templates in `templates/<type>.md` and `templates/<type>/<variant>.md`, and read their heading list.
- `services/catalog/catalog.py`: build the catalog from **live adapter reads**.
  - Cache keyed by head SHA.
  - File bodies cached by blob SHA.
  - Conditional requests where the host supports them.
- Validation warnings, shown in the UI and status:
  - manifest entries pointing at missing files or sections;
  - unknown doc types;
  - templates with no default variant;
  - "no always-on rules defined".
- `GET /api/projects/{project_id}/catalog`: doc types, variants, rule sections with their scope, and warnings.

**Out of scope:** choosing rules for a request (P8).

**Tests**
- Manifest parsing, both valid and every kind of invalid input.
- Section splitting.
- Template discovery.
- Cache hit and miss.
- A repo with no manifest gets conventions plus the warning.

**Acceptance**
- The catalog endpoint for a sample golden repo lists the expected doc types, rule sections and warnings.

---

## P8: Rule selection and request inference
**Goal:** given free text plus optional explicit fields, pick the rules and template (§B3-6, §C).

**Scope**
- `services/context/inference.py`:
  - match doc-type aliases and tag vocabulary, then use embedding similarity against template titles, headings and rule scopes;
  - explicit fields always win;
  - return the best match with a confidence score and runner-up candidates.
- `services/context/selection.py`:
  - `always` sections first;
  - then `applies_to` matches (an absent dimension means any; order by priority, then file, then section);
  - then untagged sections by relevance (section embeddings cached by blob SHA + section hash, with a threshold, max count and budget);
  - every selected rule reports `matched_on` and its score.
- Template variant: the most specific match wins, otherwise the default.
- `POST /api/context/preview`: returns only the inference, rules and template. This is a debugging aid before P9.

**Out of scope:** knowledge retrieval and budgets across sections (P9).

**Tests**
- Each selection level.
- An explicit override beats inference.
- An ambiguous request returns the best match plus candidates.
- Variant selection.
- A fake embedder keeps the tests deterministic.

**Acceptance**
- A set of hand-written requests against the sample repo picks the expected doc type, template variant and rules, and the team reviews the results.

---

## P9: `get_context` API, sub-queries, rerank, tools
**Goal:** the full response ASTRA and the LLM will use (§F, §C1).

**Scope**
- `POST /api/context`, taking `project_id`, `text`, and optional `doc_type`, `stage`, `tags` and `budget`. It returns the typed response from §F1.
- Template-section sub-queries: one hybrid search per template heading plus the request text, results grouped by section, deduplicated across sections.
- Reranker: bge-reranker-base through fastembed's cross-encoder support (check the model is available).
  - It re-scores the top ~30 candidates.
  - It has a time budget, and `status.rerank` reports when it was skipped.
- Token budgets are filled in this order:
  1. always rules
  2. template
  3. scope rules
  4. relevance rules
  5. knowledge

  Anything truncated is flagged.
- Degraded modes:
  - Qdrant down: rules and template are still returned;
  - host down: the cached catalog is used and marked `stale`.
- `services/tools/`: Claude tool schemas `get_document_context`, `search_project_data` and `validate_document_name` as thin wrappers, plus a dispatcher. Repo content is clearly labelled as data.
- The nomenclature validator, once the `nomenclature.md` format is known (open question).

**Out of scope:** API authentication, parent-section expansion.

**Tests**
- Response shape.
- Budget order and truncation flags.
- Rerank skipped under the budget.
- Each degraded mode.
- Tool dispatch.

**Acceptance**
- For three real requests (for example a BRD for payments at the design stage), the team reviews the response and agrees it holds the right rules, template and evidence.

---

## P10: GitLab and Bitbucket adapters
**Goal:** the remaining hosts (§D2). Can run in parallel with P5-P9.

**Scope**
- `services/sources/gitlab.py`:
  - nested groups;
  - `PRIVATE-TOKEN` for the REST API, `oauth2:<pat>` for git;
  - the repository files and tree APIs.
- `services/sources/bitbucket.py`:
  - Cloud API 2.0;
  - access token as Bearer.
- Both must pass the contract suite.

**Acceptance**
- Connect a real repo on each host and run a sync and a search.

---

## P11: Evaluation set and tuning
**Goal:** replace the guessed defaults with measured ones (review R13).

**Scope**
- A small set of real requests (20-50) per sample org, each with the rules, template and evidence it should return.
  Starter list for retrieval only (22 ecommerce questions with expected sources and facts): [eval-questions.md](eval-questions.md).
- A script that reports recall@k for evidence and for rules.
- Tune the relevance threshold, budgets and rerank candidate count. Record the results in the CHANGELOG.
- Use the set as a check before merging any change to chunking, models or selection.

---

## Later (not phased yet)
- Webhooks per host (the adapter slot exists from P2).
- Hash-diff incremental ingest.
- PDF, xlsx and pptx loaders.
- Redaction stage.
- A secrets store instead of `.env`.
- API authentication and gateway claims (review ADR-05).
- Parent-section expansion.
- Front-matter filters in the API.
- GitHub App and service-principal credentials.

## Open questions to settle before the phase that needs them
| Question | Needed by |
|---|---|
| Case-sensitivity of ADO paths for the required root items | P3 |
| Where the SQLite file lives in deployment, and whether it should be Postgres instead | P4: **settled for now**: SQLite at `data/astra.db`, `ASTRA_DB_PATH` override, single app instance; Postgres later (expect transaction, locking and migration work, not only config) |
| Nightly sync time and time zone | P5: **settled**: 02:00 UTC by default, `ASTRA_SYNC_DAILY_AT` override (named time zones would need `tzdata` on Windows) |
| Real template doc types and filenames, and who owns `golden.yaml` | P7 |
| ASTRA stage names (the `stages` vocabulary) | P8 |
| `nomenclature.md` format (for the validator) | P9 |
| API authentication for deployed use | Before the first deployment |
