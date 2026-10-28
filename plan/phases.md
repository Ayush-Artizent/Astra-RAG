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
| P6 | Front-matter-aware ingestion | S | P0 | Front-matter in payload, stripped from chunk text |
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
- `services/sources/github.py`: the existing `github_client` and `cloner` logic, moved here.
- `routes.py`, `validator` and ingestion call the adapter, not `github_client` or `cloner` directly.
  - `chunker._source_url` uses `adapter.citation_url`.
- `tests/sources/contract.py`: a shared contract test suite every adapter must pass, using faked HTTP and a local bare git repo.

**Out of scope:** new hosts, ETag caching (P7).

**Tests**
- The GitHub adapter passes the contract suite.
- The route tests still pass unchanged.

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

---

## P6: Front-matter-aware ingestion
**Goal:** make use of the YAML front-matter in project-data Markdown files (§E1). Can start any time after P0.

**Scope**
- Add `pyyaml` with `uv add pyyaml`.
- `md_chunker` / `loader`:
  - detect a leading `---` block;
  - parse it safely (`yaml.safe_load`);
  - strip it from the text and line-number calculations, keeping line numbers correct.
- Copy scalar and list fields into the payload under `fm.<key>`, and index common keys (`fm.type`, `fm.status`, `fm.tags`).
- Bad YAML: index the file without front-matter and add a warning.

**Out of scope:** front-matter filters in the search API (P9 or later).

**Tests**
- Front-matter is stripped.
- Fields appear in the payload.
- Line numbers still match the original file.
- Bad YAML produces a warning and ingestion continues.

**Acceptance**
- Ingest a repo with front-matter files. Chunks show `fm.*` fields, and no chunk text starts with `---`.

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
| Where the SQLite file lives in deployment, and whether it should be Postgres instead | P4 |
| Nightly sync time and time zone | P5 |
| Real template doc types and filenames, and who owns `golden.yaml` | P7 |
| ASTRA stage names (the `stages` vocabulary) | P8 |
| `nomenclature.md` format (for the validator) | P9 |
| API authentication for deployed use | Before the first deployment |
