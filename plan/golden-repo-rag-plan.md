# Plan: Golden Repo RAG, end to end (requirements captured; deliverable = `plan/` folder of docs)

> **Status: draft for team discussion (2026-10-28).** These requirements were gathered with Ayush Kumar Rai.
> Nothing in this file is built yet. The 12-file `plan/` breakdown described below will be written after the team agrees.

## Context
Astra-RAG today connects a golden repo, validates 4 required root items, clones it, and ingests `project-data/` into
Qdrant (W1 done). W2 (rules/templates tool) and W4 (sync) exist only as task lists in `timeline/TASKS.md`.
The user asked for a detailed end-to-end plan for the Golden Repo RAG part:
- what an org puts in the repo (guidance, not restriction);
- always rules vs scenario rules vs templates;
- adapters that refresh the index when the tracked branch changes, with a configurable branch;
- the ingestion and retrieval strategies;
- what to build, how, and what each piece helps with.

Working mode: **requirements gathering first, step by step. Nothing is written to the repo until the user approves.**
The final deliverable is documentation only: a `plan/` folder (files listed at the end). No code.

## Requirements captured (2026-10-28)

### A. Golden repo contract
1. Required (these block a connect): `policies.md`, `nomenclature.md`, `templates/`, `project-data/`. They are case-sensitive and
   defined in `config.REQUIRED_FILES/FOLDERS`.
2. Optional `golden.yaml` at the root. It holds the rule scopes, template variants, doc-type aliases, tag vocabulary and
   project-data hints. Content files stay clean, with no tags inside the markdown.
3. **Strictness: warn and keep going.** Anything beyond the 4 required items (a broken `golden.yaml`, an unknown doc
   type, a manifest entry pointing at a missing section) produces a warning in the UI and status, and that item falls
   back to conventions.
4. Templates are **Markdown only**. Variants by scenario: `templates/<type>.md` or `templates/<type>/<variant>.md`. The
   variant's scope is declared in `golden.yaml`, with one `default`. The template's headings define its sections.

### B. Rules model
1. Rule files hold **many rules each**. A rule is a heading section. This applies to `policies.md`,
   `nomenclature.md` and any `rules/**.md`.
2. **Scoping lives in `golden.yaml`**, keyed by file and section heading:
   ```yaml
   rules:
     - file: policies.md
       section: "Data handling"
       always: true                      # every call
     - file: rules/security.md
       section: "R-12 Payment data retention"
       applies_to: {doc_types: [BRD, SPEC], stages: [design], tags: [payments]}
   # every section not listed is chosen by relevance to the query
   ```
3. Three selection levels:
   - `always` sections are included on every call;
   - `applies_to` sections are included when doc type, stage and tags match;
   - **untagged sections are chosen by relevance to the query.** This applies even with no `golden.yaml`.
4. **Risk to document.** Nothing is guaranteed unless it is marked `always`. A repo without `golden.yaml` has no
   guaranteed rules. Mitigation: a validation warning "no always-on rules defined", shown in the UI and status, plus
   onboarding guidance telling orgs to mark their must-apply sections.
5. Scenario dimensions are **doc type, ASTRA stage and domain/tags**. Matching works like this:
   - every dimension given in `applies_to` must match;
   - an absent dimension means "any";
   - order is `priority`, then file, then section;
   - each selected rule reports `matched_on` (`always` | `scope` | `relevance` + score).
6. Relevance selection for untagged sections:
   - sections are embedded with the same bge model, cached by blob SHA + section hash;
   - scored by hybrid similarity to the query;
   - kept if above a threshold, up to a max count and token budget;
   - scores are reported in the response.

### C. Request and inference
1. Callers: **both** the ASTRA backend (structured HTTP API) and the LLM (tool calls). There is one API, and the tool schemas are thin wrappers over it.
2. Input: `project_id` plus **free text**. Optional explicit `doc_type`, `stage` and `tags`, which **win over inference**.
3. Inference uses **rules + embeddings, with no LLM**:
   - match against the doc-type aliases and tag vocabulary from `golden.yaml` and template filenames;
   - then compare by embedding similarity against template titles/headings and rule scopes.
4. Ambiguity: **pick the best match and report it.** The response lists the inferred `doc_type`, `stage` and `tags`, each
   with a confidence score and its runner-up candidates, so the caller can re-ask with explicit fields.

### D. Repos, projects, hosts, branches, sync
1. Several golden repos per org. Each **ASTRA project is bound to exactly one golden repo** (a repo can serve many
   projects). This needs a `project_id → repo` binding store. Rules, templates and search for a call all come from that one repo.
2. Hosts: **Azure DevOps first**, then GitHub/GHE (moved behind the port), then GitLab, then Bitbucket.
3. **Adapters are first-class and reusable** for other pipelines (for example the code plane), and must not be cut down.
   - They form a standalone `services/sources/` package with a `SourceAdapter` port, a credential interface, and contract tests per host.
   - The port covers both paths:
     - **sync**: `resolve_head`, `fetch_at`, `is_ancestor`, `citation_url`;
     - **live reads**: `list_dir`, `read_file`, `head_sha`, with ETag/conditional caching.
   - The `verify_webhook` slot is reserved for later.
4. Auth: a **read-only PAT per repo, for every host**, behind the credential interface (apps/service principals later).
   Each adapter builds its own git `http.extraheader`, passed through `GIT_CONFIG_*` env vars (the current cloner pattern):
   - ADO: Basic auth with an empty user;
   - GitLab: `PRIVATE-TOKEN` / `oauth2:`;
   - Bitbucket: Bearer.
5. **Rules and templates are read live from the host** (decided). Bodies are cached by blob SHA, and the head SHA is
   checked with a conditional request. The response states the rules commit and the index commit, which can differ by up to a day.
6. Tracked branch: **set by an admin in the UI/API at connect time** (default = the repo's default branch) and changeable later.
   A change triggers a full rebuild. The cloner must clone that branch explicitly (today it takes the default).
7. Freshness: **daily or manual.** Triggers are a nightly scheduled sync and "Sync now". Webhooks are not in the first build.
8. Deployed with a URL the hosts can reach, so webhooks can be added later without redesign.

### E. Ingestion
1. project-data is **mostly Markdown, structured with headings, often with YAML front-matter.**
   - Parse front-matter and copy its fields into the chunk payload as filterable keys.
   - Strip front-matter from the chunk text. This is a current `md_chunker` gap: the `---` block is treated as body text.
   - Chunk **per heading section** (own heading path), **per CSV row** (`row_key`), parse header lines (email From/Date/Subject,
     meeting Date/Attendees, `_Owner · date_`) into `doc_type` / `doc_date` / `doc_meta`, and flag open items. Done in P6 (2026-10-28).
   - Omit horizontal-rule lines (`---`, `***`, `___`) from chunk and embedded text. They are decoration, not content, and not a
     chunk boundary (chunks still split only on headings and size). Table separator rows, code fences and setext underlines
     are left alone. Done in P6 (2026-10-28).
   - **No recency or authority preference:** date and doc type are information for the LLM, never a ranking, filter or boost.
   - Keep md/txt/csv/docx. PDF, xlsx, pptx and OCR come later, on demand.
2. Size: **under 100 files per repo.** The first-build sync is:
   - skip if the head SHA is unchanged;
   - otherwise do a full rebuild into a new versioned collection and **swap an alias**, so search never sees an empty index
     (today `store.recreate` drops the collection first).
   - Hash-diff incremental ingest is a later optimisation.
3. Redaction is unlikely to be needed. It is a later item, with a stage slot kept in the pipeline.
4. Safety fix: skip symlinks and any path resolving outside the clone. The current `loader.py` `is_file()` follows
   links, so a repo could expose `.env` (which holds the PATs) through search.

### F. Retrieval
1. The response has typed sections (review §8.7):
   ```
   {inferred:{doc_type,stage,tags,confidence,candidates}, snapshot:{rules_commit,index_commit},
    rules:[{file,section,text,matched_on,score?,source_url}], template:{path,variant,text,sections[]},
    knowledge:{by_section:{<template heading>:[evidence]}, general:[evidence], total_count, truncated},
    status:{rules,knowledge,rerank}}
   ```
2. Knowledge retrieval:
   - hybrid dense + BM25 with RRF (existing `store.search`), filtered to the project's repo;
   - **template-section sub-queries** (each template heading plus the request text becomes one query, results grouped per section);
   - a **reranker** (bge-reranker-base) on the top ~30, with a time budget (skipping it is reported);
   - dedupe across sections;
   - **return every relevant match with its `doc_date`, `doc_type` and `source_url`; do not prefer newer sources, the LLM resolves conflicts**;
   - token budgets filled in this order: always rules, template, scope rules, relevance rules, knowledge. Anything truncated is flagged.
3. Later: parent-section expansion, front-matter filters in the API, an eval set (review R13).

### Open (to settle while writing the docs)
- Real template doc types/filenames and `nomenclature.md` format (W2.1/W2.3b, still open).
- Who owns `golden.yaml` changes and how they're reviewed.
- Where project→repo bindings and repo settings live (SQLite next to sync state is the proposal).
- PAT storage: today `.env`; target a secrets store. Several repos and hosts make `.env` keys host-aware.
- API authentication for deployed use (review ADR-05 gateway claims).
- Relevance threshold and budget defaults (set after measuring on a sample repo).

## Gaps in current code this plan must address (for accuracy in the docs)
- `github_client.parse_repo_url` assumes `host/owner/name`. ADO is `dev.azure.com/{org}/{project}/_git/{repo}` and GitLab has
  nested groups, so `RepoRef` needs a host kind plus a full path.
- `token_store._key` and `store.collection_name` use only `owner__name`, so two hosts would collide. The key must include the host.
- `cloner.py` uses a GitHub-specific header and the default branch. Auth and branch handling move into the adapter.
- `validator.find_missing` takes a GitHub contents listing. It should take the adapter's `list_dir("/")`.
- `pipeline` status is in memory, so it is lost on restart. Persist it with the sync state.
- ADO API notes:
  - `_apis/git/repositories/{repo}` returns defaultBranch;
  - `items?scopePath=/&recursionLevel=OneLevel` lists a folder;
  - `refs?filter=heads/{b}` gives the head;
  - `items?path=..&versionDescriptor.version=..` reads a file;
  - permalink format `?path=..&version=GC{sha}&line=..`;
  - check letter-case behaviour against the case-sensitive required items.

## Deliverable: `plan/` folder (written only after approval)
| File | Content |
|---|---|
| `README.md` | Overview, end-to-end Mermaid diagram (Context path + Knowledge path → one response), glossary, index |
| `01-golden-repo-contract.md` | §A plus the full `golden.yaml` v1 schema and example, conventions, warning list, org onboarding checklist |
| `02-rules-model.md` | §B: three levels, matching algorithm, relevance selection, risk and mitigation, worked examples |
| `03-request-and-inference.md` | §C: inputs, inference steps, confidence/candidates, explicit overrides |
| `04-sources-and-adapters.md` | §D: `SourceAdapter` + credential ports (signatures), ADO-first notes, host matrix, contract tests, `RepoRef` redesign |
| `05-branch-and-sync.md` | §D6-8 + §E2: tracked branch config, nightly/manual triggers, locking, state store, alias swap, failure handling, later webhooks |
| `06-ingestion.md` | §E: loader, front-matter, section/row chunking, header metadata, payload fields, versioning, safety fix, later formats/redaction |
| `07-retrieval.md` | §F: response contract, sub-queries, rerank, budgets, degraded modes, citations |
| `08-api-and-tools.md` | Endpoints (context, catalog, sync, bindings, repo settings) and Claude tool schemas as wrappers |
| `09-security-and-ops.md` | PATs, symlinks, untrusted content as data, observability, runbook |
| `10-roadmap.md` | Workstreams in dependency order with acceptance criteria and tests; mapping of the old W2/W4 tasks; review R#/ADR# mapping |
| `11-open-questions.md` | The "Open" list above, with owner and when each is needed |

Proposed build order for `10-roadmap.md`:
1. Symlink fix.
2. `sources/` port + ADO adapter + `RepoRef`/keys redesign.
3. Bindings + repo settings + branch config.
4. `golden.yaml` parser + rule/section catalog (live reads).
5. Inference + rule selection + template variants.
6. Sync (nightly/manual, alias swap, state).
7. Front-matter ingestion.
8. `get_context` with sub-queries + rerank.
9. GitHub, GitLab and Bitbucket adapters.
10. Eval set.

Also on approval, per CLAUDE.md:
- a CHANGELOG line;
- `TASKS.md` pointing to `plan/10-roadmap.md`;
- `CURRENT_STATE.md` branch-name fix (`goldan-repo`) and layout additions (`token_store.py`, `plan/`);
- a README Structure line.

## Verification (for the docs)
- Every claim about current behaviour is checked against the code (e.g. `store.recreate`, `loader` symlinks, cloner branch, key collisions).
- Every existing W2/W4 task in `TASKS.md` maps into `plan/10-roadmap.md`, with none lost.
- Mermaid blocks render in a VS Code/GitHub preview.
- No code changes, so the existing tests still pass (`uv run python -m unittest discover -s tests -t .`).
