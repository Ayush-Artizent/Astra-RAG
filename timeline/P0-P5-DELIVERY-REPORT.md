# Delivery report: phases P0 to P5

_Written 2026-10-28 against branch `goldan-repo-re-guru`. P0-P4 are commits `f7ed92a` to `36cd57c`; **P5 is in the working tree and not committed yet**._
_Later work is not covered here: P7 (golden catalog) was delivered 2026-10-30, see `timeline/CHANGELOG.md` and `timeline/CURRENT_STATE.md`._
_Plan being checked: [plan/phases.md](../plan/phases.md). Test run on the working tree: **177 tests, all pass, 1 skipped** (a symlink test that cannot run on Windows). At `36cd57c` (end of P4) it was 145; at `4607ba9` (end of P3) 105._

This report explains, in plain English, what has been built in phases P0 to P5, how each part works, and
exactly where the code and tests are. Every claim links to a file and line, so you can open it and check it yourself.
Links are relative to this file and open in VS Code or on GitHub.

**All line links point at the current working tree (P5 included).** Where a later phase replaced code that an earlier
phase delivered (P4: `routes.py` and the in-memory ingestion status; P5: the clone inside connect, the 409 guard and
the drop-then-rebuild of the Qdrant collection), the earlier section says so; `git show <commit>` shows the original.

---

## Contents
1. [How to use this report](#1-how-to-use-this-report)
2. [The app in one page (end-to-end flow today)](#2-the-app-in-one-page-end-to-end-flow-today)
3. [Phase P0: Safety fixes and doc cleanup](#3-phase-p0-safety-fixes-and-doc-cleanup)
4. [Phase P1: Host-aware repo identity](#4-phase-p1-host-aware-repo-identity)
5. [Phase P2: Source adapter port + GitHub adapter](#5-phase-p2-source-adapter-port--github-adapter)
6. [Phase P3: Azure DevOps adapter](#6-phase-p3-azure-devops-adapter)
7. [Phase P4: Repo registry, project bindings and tracked branch](#7-phase-p4-repo-registry-project-bindings-and-tracked-branch)
8. [Phase P5: Sync (nightly and Sync now) with alias swap](#8-phase-p5-sync-nightly-and-sync-now-with-alias-swap)
9. [Extra change shipped with P3: token saved as soon as the host accepts it](#9-extra-change-shipped-with-p3-token-saved-as-soon-as-the-host-accepts-it)
10. [Work done before the phases (W0, W1) that P0-P5 build on](#10-work-done-before-the-phases-w0-w1-that-p0-p5-build-on)
11. [Security controls: where each one is enforced](#11-security-controls-where-each-one-is-enforced)
12. [Reference: endpoints, config, stored data, dependencies](#12-reference-endpoints-config-stored-data-dependencies)
13. [Test inventory](#13-test-inventory)
14. [Open items, gaps and limitations](#14-open-items-gaps-and-limitations)
15. [How to verify this yourself](#15-how-to-verify-this-yourself)

---

## 1. How to use this report

- **Each phase section has the same layout:** goal, what was delivered, how it works, a "where" table
  (file and line links), the tests that prove it, and a plan-versus-delivered checklist.
- **Commits:** one commit per phase. Use `git show <hash>` to see exactly what each phase changed.

| Phase | Commit | Files changed | Summary from `git show --stat` |
|---|---|---|---|
| Planning | `f450d64` | 4 | Added `plan/phases.md` |
| P0 | `f7ed92a` | 8 | +156 / -22 |
| P1 | `764eb13` | 21 | +265 / -102 |
| P2 | `e994236` | 32 | +799 / -186 |
| P3 | `4607ba9` | 17 | +387 / -35 |
| P4 | `36cd57c` | 34 | +1954 / -177 (includes this report) |
| P5 | not committed yet | 28 (7 new) | +1382 / -199 (code, tests and docs, from `git diff --stat` plus the new files; this report not counted) |

- **Status words used below:** ✅ done and tested · ⚠️ done in code but not verified against a real host · ❌ not done.

---

## 2. The app in one page (end-to-end flow today)

The user opens the page, enters a repo URL (GitHub, GitHub Enterprise or Azure DevOps), a personal access token (PAT)
and optionally a branch to track, and clicks **Check & sync**. The route
[`validate_and_clone`](../src/astra_rag/routes.py#L49-L66) is thin: it calls
[`connections.connect`](../src/astra_rag/services/connections.py#L25-L48), which checks and registers the repo, and then
hands the queued run to the background sync worker. Since P5 nothing is cloned inside the request.

| Step | What happens | Where |
|---|---|---|
| 1 | The browser posts `{url, token, branch}` to `POST /api/validate-and-clone`. | [app.js:143-173](../src/astra_rag/static/app.js#L143-L173) |
| 2 | The URL is parsed into a `RepoRef` (host kind, host, path parts, name). The adapter registry checks scheme and host, then hands the rest of the URL to that host's adapter. | [connections.py:30](../src/astra_rag/services/connections.py#L30) → [registry.py:19-27](../src/astra_rag/services/sources/registry.py#L19-L27) |
| 3 | The token is the one typed in, or, if the field is blank, the one saved in `.env` for this repo. No token at all gives a 400. | [connections.py:31-34](../src/astra_rag/services/connections.py#L31-L34) → [token_store.get_token](../src/astra_rag/services/token_store.py#L111-L115) |
| 4 | A typed branch name is checked against a strict pattern **before any host call** (no leading `-`, no `..`, ...). | [connections.py:35](../src/astra_rag/services/connections.py#L35) → [rules.check_branch_name](../src/astra_rag/services/registry/rules.py#L8-L13) |
| 5 | The host's adapter is picked, with the token wrapped in a `PatCredential`. The branch is the typed one, else the repo's saved tracked branch, else the host's default branch. | [connections.py:37-38](../src/astra_rag/services/connections.py#L37-L38) → [repos.tracked_branch](../src/astra_rag/services/registry/repos.py#L10-L13) |
| 6 | `head_sha(branch)` confirms the branch exists (404 "Branch not found" otherwise). Its commit is returned to the browser as the head seen at connect. | [connections.py:39](../src/astra_rag/services/connections.py#L39) |
| 7 | The root **of that branch** is listed. That worked, so the host accepted the token: a typed token is saved to `.env` with the cleaned URL (`adapter.web_url`). | [connections.py:40-42](../src/astra_rag/services/connections.py#L40-L42) → [token_store.save](../src/astra_rag/services/token_store.py#L95-L103) |
| 8 | The listing is checked for `policies.md`, `nomenclature.md`, `project-data/` and `templates/` (exact case). Anything missing → HTTP 422 listing the missing items. Nothing is registered. | [connections.py:43-45](../src/astra_rag/services/connections.py#L43-L45) → [validator.find_missing](../src/astra_rag/services/validator.py#L5-L11) |
| 9 | **One SQLite transaction** registers or updates the repo (only a real branch change bumps `config_version`) and queues a forced run. If a run is already queued or running, no second run starts: the request is folded into one follow-up run and the response says `pending` (P4 answered 409). | [connections.py:47](../src/astra_rag/services/connections.py#L47) → [runs.register_and_queue](../src/astra_rag/services/registry/runs.py#L15-L34) → [runs._queue](../src/astra_rag/services/registry/runs.py#L46-L60) |
| 10 | The route gives the run to the sync worker and answers straight away with `branch`, `commit_sha` and `ingestion: {slug, run_id, state}`. | [routes.py:56-66](../src/astra_rag/routes.py#L56-L66) → [sync.start](../src/astra_rag/services/sync/service.py#L39-L40) → [worker.submit](../src/astra_rag/services/sync/worker.py#L29-L34) |
| 11 | Background, in the worker: the tracked branch is shallow-cloned (`--branch <b> --single-branch`) into `temp_storage/<slug>/`, replacing any older clone, and the commit SHA goes on the run. A clone failure finishes the run as `failed` and records `source_error` on the repo. | [service.execute](../src/astra_rag/services/sync/service.py#L43-L52) → [service._build](../src/astra_rag/services/sync/service.py#L55-L69) → [cloner.clone_repo](../src/astra_rag/services/cloner.py#L12-L18) → [git.git_clone](../src/astra_rag/services/sources/git.py#L11-L34) |
| 12 | Background: load `project-data/` → chunk → embed → store in a **new version collection** → check the point count → switch the repo's alias to it → drop older versions. Progress goes to the run row; a `done` run becomes the repo's indexed build. Search keeps using the previous version until the switch. | [pipeline.run_ingestion](../src/astra_rag/services/ingestion/pipeline.py#L34-L56), [_ingest](../src/astra_rag/services/ingestion/pipeline.py#L59-L102), [runs.finish_run](../src/astra_rag/services/registry/runs.py#L83-L95) |
| 13 | When the run ends, a follow-up that was folded in meanwhile is started. | [service._follow_up](../src/astra_rag/services/sync/service.py#L72-L80) |
| 14 | The browser polls `GET /api/ingestion-status/{slug}` every 1.5 s (read from SQLite) until done or failed, then refreshes the repos table. | [app.js:127-141](../src/astra_rag/static/app.js#L127-L141) → [routes.py:69-74](../src/astra_rag/routes.py#L69-L74) → [runs.latest_run](../src/astra_rag/services/registry/runs.py#L132-L136) |
| 15 | The repos table (`GET /api/repos`) shows each repo's tracked branch, indexed commit and time, last check, sync status, a **Sync now** button and the next nightly check. | [app.js:32-75](../src/astra_rag/static/app.js#L32-L75) → [routes.py:77-79](../src/astra_rag/routes.py#L77-L79) → [repos._view](../src/astra_rag/services/registry/repos.py#L92-L114) |
| 16 | `POST /api/search` with `{slug, query}` runs a hybrid search through that repo's alias. | [routes.py:105-109](../src/astra_rag/routes.py#L105-L109) → [pipeline.search](../src/astra_rag/services/ingestion/pipeline.py#L105-L113) |

At startup the app's lifespan ([`__init__.py:15-30`](../src/astra_rag/__init__.py#L15-L30)) takes the single-instance
lock, runs [`registry.startup`](../src/astra_rag/services/registry/__init__.py#L6-L9) (brings the database schema up to
date and marks runs a previous process left `queued`/`running` as `failed`), runs the index recovery, then starts the
sync worker and the nightly scheduler (P5, [§8](#8-phase-p5-sync-nightly-and-sync-now-with-alias-swap)).

**Other ways a sync starts (P5):** the **Sync now** button (`POST /api/repos/{slug}/sync`), a branch change in
`PUT /api/repos/{slug}/settings`, the **nightly check** and the **startup catch-up**. All of them go through
[`sync.request_sync`](../src/astra_rag/services/sync/service.py#L18-L36) and then the same steps 11-13.

**Errors:** any user-facing failure raises `AppError(message, status)` ([errors.py](../src/astra_rag/services/errors.py#L1-L7)).
One handler turns it into `{"ok": false, "error": "..."}` with that status
([`__init__.py:38-40`](../src/astra_rag/__init__.py#L38-L40)).

**Layering (who is allowed to talk to what):**

```
routes.py  (thin HTTP layer)
   |-- services/connections.py       -> connect flow and branch changes (uses everything below)
   |-- services/sync/                -> P5: request_sync / execute (clone + ingest + follow-up), worker, scheduler,
   |                                    reconcile (startup recovery), instance (single-instance lock)
   |-- services/registry/            -> SQLite: repos, project bindings, ingestion runs (all SQL lives here)
   |       '-- db.py (connections, transactions, migrations), repos.py, runs.py, rules.py
   |-- services/sources/registry.py  -> picks an adapter for the URL's host
   |       |-- sources/github.py        (GitHub + GitHub Enterprise)
   |       |-- sources/azure_devops.py  (Azure DevOps)
   |       '-- shared: base.py (the port), credentials.py, git.py, http.py, json_reply.py, errors.py
   |-- services/validator.py         -> pure check of a root listing
   |-- services/cloner.py            -> picks temp_storage/<slug>, deletes old clone, calls adapter.clone
   |-- services/token_store.py       -> .env read/write
   '-- services/ingestion/pipeline.py -> loader -> chunker -> embedder -> store (Qdrant); progress -> registry.runs
```

Routes, the validator and ingestion never call a Git host directly. Only adapters do (this is the P2 rule).
Note the two "registries": `services/sources/registry.py` maps a host to an adapter; `services/registry/` is the P4
database.

---

## 3. Phase P0: Safety fixes and doc cleanup

**Commit:** `f7ed92a` · **Status:** ✅ done (one acceptance check verified on Linux only, see below)

### Goal
Close a real security hole before anything else. A "golden" repo is untrusted input. If it contained a symlink such as
`project-data/x.md -> ../../../.env`, the loader would have followed it, indexed the `.env` file (which holds PATs),
and made the tokens searchable through `/api/search`.

### What was delivered
1. The loader never follows symbolic links, never follows Windows junctions, and skips any path whose real location is
   outside the clone. Each one is reported as skipped with a reason. Nothing is dropped silently.
2. As a second layer, every clone is made with `core.symlinks=false`, so git writes links out as small plain text
   files instead of real links.
3. Doc fixes: branch name, `token_store.py` added to the layout, TASKS W2.5 wording about where the token is kept.

### How it works
- **Walking the folder:** the loader uses `Path.walk()`, which does not follow links into folders by default.
  For every sub-folder and file it calls `_check_link`.
  ([loader.py:23-31](../src/astra_rag/services/ingestion/loader.py#L23-L31))
- **The check itself:** `_check_link` skips a path if it is a symlink, **or** a junction, **or** its `resolve()`d
  location is not inside the resolved clone root. It records a `SkippedFile` with the reason
  `"symbolic link or outside the repository (not followed)"`.
  ([loader.py:37-42](../src/astra_rag/services/ingestion/loader.py#L37-L42), reason text at [loader.py:8](../src/astra_rag/services/ingestion/loader.py#L8))
- **Pruning:** linked or hidden folders are removed from `dirnames` in place, so the walk never goes inside them.
  ([loader.py:25-27](../src/astra_rag/services/ingestion/loader.py#L25-L27))
- **`project-data` itself as a link:** if the whole `project-data` folder resolves outside the clone, nothing is
  loaded and the folder is reported as skipped.
  ([loader.py:18-21](../src/astra_rag/services/ingestion/loader.py#L18-L21))
- **"Inside" test:** `path.resolve().is_relative_to(repo_root)`. An `OSError` while resolving counts as outside.
  ([loader.py:59-64](../src/astra_rag/services/ingestion/loader.py#L59-L64))
- **Clone layer:** `core.symlinks=false` is passed to git through `GIT_CONFIG_KEY_1` / `GIT_CONFIG_VALUE_1`
  environment variables. It was added in `cloner.py` in P0 and moved to the shared `git.py` in P2.
  ([git.py:14](../src/astra_rag/services/sources/git.py#L14), [git.py:19-24](../src/astra_rag/services/sources/git.py#L19-L24))

### Where

| What | File and lines |
|---|---|
| Symlink, junction and outside-the-clone checks | [loader.py:11-42](../src/astra_rag/services/ingestion/loader.py#L11-L42), [loader.py:59-64](../src/astra_rag/services/ingestion/loader.py#L59-L64) |
| `core.symlinks=false` on clone | [git.py:19-24](../src/astra_rag/services/sources/git.py#L19-L24) |
| Skipped files shown in the UI | [app.js:116-125](../src/astra_rag/static/app.js#L116-L125) (`skipped <path>: <reason>`) |
| Skipped files in the status API | [pipeline.py:24](../src/astra_rag/services/ingestion/pipeline.py#L24), [pipeline.py:66-68](../src/astra_rag/services/ingestion/pipeline.py#L66-L68) |

### Tests

| Test | What it proves |
|---|---|
| [test_ingestion.py:119-152](../tests/test_ingestion.py#L119-L152) `LoaderSymlinkTests` | Sets up a fake "outside" folder holding `secret.md` with a fake token. |
| [test_ingestion.py:134](../tests/test_ingestion.py#L134) `test_file_link_is_skipped_and_reported` | A file link to the secret is not loaded and is reported as "symbolic link". |
| [test_ingestion.py:140](../tests/test_ingestion.py#L140) `test_folder_link_is_not_followed` | A folder link is not walked into. |
| [test_ingestion.py:146](../tests/test_ingestion.py#L146) `test_project_data_itself_linked_outside_loads_nothing` | A `project-data` that points outside loads nothing. |
| [test_ingestion.py:105-116](../tests/test_ingestion.py#L105-L116) `symlink_or_skip` | Skips cleanly when the OS will not create symlinks (this is the 1 skip on Windows). |
| [tests/sources/test_git.py:25](../tests/sources/test_git.py#L25) `test_disables_symlinks_and_keeps_the_header_out_of_args` | The clone env sets `core.symlinks=false`. |

### Plan vs delivered

| Plan item ([phases.md P0](../plan/phases.md)) | Status |
|---|---|
| Skip symlinks (`is_symlink()`) | ✅ (also junctions, which the plan did not list) |
| Skip any file whose `resolve()` is outside the clone | ✅ |
| Report each as skipped with a reason | ✅ |
| Clone with `core.symlinks=false` via `GIT_CONFIG_*` | ✅ |
| Fix branch name in docs | ✅ at the time, but has drifted again (fixed again in P4, see [§13](#14-open-items-gaps-and-limitations)) |
| Add `token_store.py` to the layout | ✅ |
| Fix TASKS W2.5 token wording | ✅ |
| Test: symlink to outside file is skipped; skip cleanly on Windows | ✅ |
| Acceptance: on Linux/macOS a `project-data/x.md -> ../../../.env` link does not appear in search | ⚠️ The CHANGELOG says the file-symlink case was verified on Linux in Docker. On Windows the test is skipped. |

---

## 4. Phase P1: Host-aware repo identity

**Commit:** `764eb13` · **Status:** ✅ done

### Goal
Before P1 a repo was identified only by `owner/name`. So `github.com/acme/golden` and a GitHub Enterprise
`git.corp.com/acme/golden` would have shared one saved token, one clone folder, one Qdrant collection and one status
entry. P1 makes the identity include the host, before any second host is added.

### What was delivered
1. A `RepoRef` with four fields: `host_kind`, `host`, `path_parts`, `name`.
2. A `slug` that includes the host, for example `github.com__acme__golden`. It is lower-case because hosts treat names
   case-insensitively.
3. The slug is now the key for all four stores: the `.env` token entry, the clone folder, the Qdrant collection and the
   ingestion status.
4. A one-off migration of old `.env` keys (`ASTRA_REPO_<OWNER>__<NAME>_*`) to the new host-aware key.
5. URLs for hosts that are not supported get a clear "not supported yet" error.
6. **API change:** the status and search endpoints now take the `slug` instead of owner and name.

### How it works
- **`RepoRef`** is a frozen dataclass. `owner` joins the `path_parts` with `/` (GitHub has one part, the owner; ADO has
  two, org and project). `full_name` is `owner/name`. ([repo_ref.py:5-18](../src/astra_rag/services/repo_ref.py#L5-L18))
- **`slug`** joins host, path parts and name with `__` and lower-cases the result.
  ([repo_ref.py:20-23](../src/astra_rag/services/repo_ref.py#L20-L23))
- **`host_kind(host)`** classifies a hostname: `github.com` → `github`; `dev.azure.com` or `*.visualstudio.com` →
  `azure_devops`; `gitlab.com` or `gitlab.*` → `gitlab`; `bitbucket.org` → `bitbucket`; **any other host → `ghe`**
  (GitHub Enterprise Server). ([repo_ref.py:26-35](../src/astra_rag/services/repo_ref.py#L26-L35))
- **Supported hosts** are listed once in [config.py:16](../src/astra_rag/config.py#L16). The URL parser rejects any
  other kind with "GitLab/Bitbucket repositories are not supported yet".
  ([registry.py:24-26](../src/astra_rag/services/sources/registry.py#L24-L26)) In P1 only `github` and `ghe` were on
  the list; P3 added `azure_devops`.
- **Where the slug is used:**

| Store | How the slug is used | Where |
|---|---|---|
| `.env` token entry | `ASTRA_REPO_` + slug with non-alphanumerics turned into `_`, upper-cased, e.g. `ASTRA_REPO_GITHUB_COM__ACME__GOLDEN_TOKEN` | [token_store.py:25-30](../src/astra_rag/services/token_store.py#L25-L30) |
| Clone folder | `temp_storage/<slug>` | [cloner.py:15](../src/astra_rag/services/cloner.py#L15) |
| Qdrant collection | `astra__<slug>` (unsafe characters turned into `_`) | [store.py:21-23](../src/astra_rag/services/ingestion/store.py#L21-L23) |
| Ingestion status | in-memory dict keyed by slug in P1; **since P4** the `repo_slug` column of the SQLite `ingestion_runs` table | [db.py:37-56](../src/astra_rag/services/registry/db.py#L37-L56), [runs.latest_run](../src/astra_rag/services/registry/runs.py#L132-L136) |
| Chunk payload | `repo_slug` and `host` fields on every chunk | [chunker.py:27-33](../src/astra_rag/services/ingestion/chunker.py#L27-L33) |

- **Legacy key migration:** every read or write of `.env` goes through `_load`, which calls `_migrate`.
  `_migrate` looks for the old `owner__name` key, and **only moves it if the URL saved with it parses to the same slug**
  (so a legacy entry that really belonged to another host is left alone). If a token is already saved under the new
  key, the new key wins. The file is then rewritten.
  ([token_store.py:33-63](../src/astra_rag/services/token_store.py#L33-L63))
- **Existing Qdrant collections and clone folders** under old names are not migrated. They are simply rebuilt on the
  next connect, as the plan allowed.

### Where

| What | File and lines |
|---|---|
| `RepoRef`, `slug`, `host_kind` | [repo_ref.py](../src/astra_rag/services/repo_ref.py) (whole file, 35 lines) |
| Supported host list | [config.py:15-16](../src/astra_rag/config.py#L15-L16) |
| "Not supported yet" error | [registry.py:16](../src/astra_rag/services/sources/registry.py#L16), [registry.py:24-26](../src/astra_rag/services/sources/registry.py#L24-L26) |
| Token key + migration | [token_store.py:25-63](../src/astra_rag/services/token_store.py#L25-L63) |
| Slug in the ingestion context | [models.py:7-28](../src/astra_rag/services/ingestion/models.py#L7-L28) `RepoContext.slug` |
| Routes take the slug | [routes.py:32-37](../src/astra_rag/routes.py#L32-L37) (`SearchRequest.slug`), [routes.py:69](../src/astra_rag/routes.py#L69), and since P4 [routes.py:82-83](../src/astra_rag/routes.py#L82-L83) |
| UI polls by slug | [app.js:127-131](../src/astra_rag/static/app.js#L127-L131) |

### Tests

| Test | What it proves |
|---|---|
| [test_validator_and_url.py:33](../tests/test_validator_and_url.py#L33) `test_github_ref_is_host_aware` | A GitHub URL gives the expected host kind, host and slug. |
| [test_validator_and_url.py:38](../tests/test_validator_and_url.py#L38) `test_same_owner_and_name_on_two_hosts_do_not_collide` | Same owner/name on two hosts → two different slugs. |
| [test_validator_and_url.py:45](../tests/test_validator_and_url.py#L45) `test_other_hosts_are_not_supported_yet` | GitLab and Bitbucket URLs are rejected. |
| [test_token_store.py:44](../tests/test_token_store.py#L44) `test_same_owner_and_name_on_another_host_has_its_own_token` | Tokens do not leak across hosts. |
| [test_token_store.py:51](../tests/test_token_store.py#L51) `test_legacy_key_is_migrated_once` | Old key moves to new key. |
| [test_token_store.py:61](../tests/test_token_store.py#L61) `test_legacy_key_of_another_host_is_left_alone` | Old key with a different host's URL is not moved. |
| [test_token_store.py:69](../tests/test_token_store.py#L69) `test_save_drops_the_legacy_entry` | Saving cleans up the old entry. |
| [test_cloner.py:23](../tests/test_cloner.py#L23) `test_clones_into_a_folder_named_after_the_host_aware_slug` | Clone folder is `temp_storage/<slug>`. |
| [test_routes.py:76](../tests/test_routes.py#L76) `test_connect_queues_a_background_sync_on_the_default_branch` (was `test_clone_queues_ingestion_with_commit_and_status_is_readable` before P4, `test_clone_queues_a_persisted_run_on_the_default_branch` before P5) | Response carries `slug: github.com__acme__golden`; status is readable by slug. |

### Plan vs delivered

| Plan item | Status |
|---|---|
| `RepoRef {host_kind, host, path_parts, name}` with stable host-aware slug | ✅ |
| Only GitHub accepted in P1; others "not supported yet" | ✅ (ADO later enabled by P3) |
| Slug used in `token_store._key`, `store.collection_name`, clone folder, status key | ✅ all four |
| One-off migration of old `.env` keys | ✅ (safer than planned: only moves when the saved URL matches) |
| Tests: two hosts → different slugs; old key migrated; old URL tests pass | ✅ |
| Acceptance: GitHub connect, ingest, search work as before | ✅ by route tests; manual run not recorded |

---

## 5. Phase P2: Source adapter port + GitHub adapter

**Commit:** `e994236` · **Status:** ✅ done (refactor, no behaviour change)

### Goal
Create one place that knows how to talk to a Git host, so the rest of the app is host-neutral and adding a host
means adding one adapter file. Move all GitHub code behind it **without changing any behaviour**.

### What was delivered
A new package [`services/sources/`](../src/astra_rag/services/sources/) with:

| File | Role |
|---|---|
| [base.py](../src/astra_rag/services/sources/base.py) | The **port**: abstract class `SourceAdapter` every host implements, plus `DirEntry` and `CloneResult`. |
| [credentials.py](../src/astra_rag/services/sources/credentials.py) | `Credential` protocol and `PatCredential`, a token wrapper that never prints the secret. |
| [registry.py](../src/astra_rag/services/sources/registry.py) | `parse_repo_url` (URL → `RepoRef`) and `adapter_for` (`RepoRef` → adapter). |
| [github.py](../src/astra_rag/services/sources/github.py) | GitHub and GitHub Enterprise adapter (the old `github_client.py` + clone logic). |
| [git.py](../src/astra_rag/services/sources/git.py) | Host-neutral `git clone`; the adapter only supplies the clone URL and auth header. |
| [http.py](../src/astra_rag/services/sources/http.py) | Shared HTTP GET helpers with consistent error mapping. |
| [errors.py](../src/astra_rag/services/sources/errors.py) | Maps HTTP status codes to safe `AppError`s. |
| [`__init__.py`](../src/astra_rag/services/sources/__init__.py) | Public surface: `PatCredential`, `adapter_for`, `parse_repo_url`, `SourceAdapter`, `CloneResult`. |

Removed: `services/github_client.py`. Moved: `RepoRef.clone_url` and `RepoRef.api_base` into the GitHub adapter;
`parse_repo_url` into the registry.

### How it works

**The port** ([base.py:25-75](../src/astra_rag/services/sources/base.py#L25-L75)). One adapter instance = one repo on
one host. It holds the `RepoRef` and an optional credential.

| Method | Purpose | Used by today |
|---|---|---|
| `parse_url(parts, kind)` (classmethod) | Turn a URL into a `RepoRef`, or raise `AppError`. | registry |
| `list_dir(path, ref)` | List a folder (`""` = root). | connect flow (root of the tracked branch, for validation) |
| `read_file(path, ref)` | Raw bytes of a file. | not yet (P7/P9) |
| `head_sha(branch)` | Current commit of a branch. | since P4: checks a branch exists (connect, settings); since P5: the sync's head check (skip if unchanged) |
| `default_branch()` | Repo's default branch. | since P4: tracked branch of a newly connected repo |
| `clone(dest, branch)` | Shallow clone. | cloner |
| `is_ancestor(base, head)` | Is `base` contained in `head`? | not yet (P5 always rebuilds in full, so it did not need it) |
| `citation_url(path, ref, lines)` | Browser link to a file at a commit, with optional line range. Needs no credential. | chunker (`source_url` on every chunk) |
| `verify_webhook(headers, body)` | Reserved. Raises 501 "not supported yet". | not yet |
| `web_url` (property, **added in P4**) | Canonical browser URL rebuilt from the `RepoRef`. | stored URL in the registry and `.env` |

The plan suggested a `Protocol`. It was built as an `ABC` instead, so `verify_webhook` can have a default body. The
plan file was updated to say so.

**Credentials** ([credentials.py](../src/astra_rag/services/sources/credentials.py)). `PatCredential` stores the token in
a `__slots__` field (no `__dict__`, so a generic dump cannot see it). `repr()` and `str()` both return
`PatCredential(<redacted>)`. The only way to get the token is `.secret()`, which an adapter calls at the moment it builds
a header ([base.py:32-35](../src/astra_rag/services/sources/base.py#L32-L35)). With no credential, network methods
raise "A personal access token is required."

**Registry** ([registry.py](../src/astra_rag/services/sources/registry.py)).
`parse_repo_url` checks the scheme is `https` and there is a hostname, classifies the host with `host_kind`, rejects
unsupported kinds, then calls that adapter's `parse_url` for the rest
([registry.py:19-27](../src/astra_rag/services/sources/registry.py#L19-L27)). `ADAPTERS` maps kind → class
([registry.py:12-14](../src/astra_rag/services/sources/registry.py#L12-L14)). A test checks that every kind in
`config.SUPPORTED_HOST_KINDS` has an adapter.

**GitHub adapter** ([github.py](../src/astra_rag/services/sources/github.py)):

| Behaviour | How | Lines |
|---|---|---|
| URL shape | `https://<host>/owner/repo(.git)(/...)`; owner and repo must match `[\w.-]+`; `.git` stripped. | [19-28](../src/astra_rag/services/sources/github.py#L19-L28) |
| API base | `https://api.github.com` for github.com, `https://<host>/api/v3` for Enterprise. | [38-42](../src/astra_rag/services/sources/github.py#L38-L42) |
| REST auth | `Authorization: Bearer <token>`. | [44-45](../src/astra_rag/services/sources/github.py#L44-L45) |
| List a folder | `GET /repos/{owner}/{repo}/contents/{path}?ref=`; root keeps the trailing `/` exactly as before. | [54-62](../src/astra_rag/services/sources/github.py#L54-L62) |
| Read a file | Same contents URL with `Accept: application/vnd.github.raw+json`. | [64-66](../src/astra_rag/services/sources/github.py#L64-L66) |
| Branch head | `GET /git/ref/heads/{branch}` → `object.sha`. | [68-71](../src/astra_rag/services/sources/github.py#L68-L71) |
| Default branch | `GET /repos/{owner}/{repo}` → `default_branch`. | [73-74](../src/astra_rag/services/sources/github.py#L73-L74) |
| Ancestry | `GET /compare/{base}...{head}`; `ahead` or `identical` means yes. | [76-80](../src/astra_rag/services/sources/github.py#L76-L80) |
| Clone | git header `Authorization: Basic base64(x-access-token:<token>)`. | [82-84](../src/astra_rag/services/sources/github.py#L82-L84) |
| Citation link | `https://<host>/{owner}/{repo}/blob/{sha}/{path}#L{start}-L{end}`. | [86-88](../src/astra_rag/services/sources/github.py#L86-L88) |
| Bad JSON shape | `_field` raises a safe 502. | [91-97](../src/astra_rag/services/sources/github.py#L91-L97) |

**Shared git clone** ([git.py:11-34](../src/astra_rag/services/sources/git.py#L11-L34)). Runs
`git clone --depth 1 [--branch X --single-branch] <url> <dest>`. The auth header and `core.symlinks=false` go in
`GIT_CONFIG_COUNT/KEY/VALUE` environment variables, so the token is **not** in the URL, not in `.git/config`, and not
in the process arguments (`-c` would show in the process list). `GIT_TERMINAL_PROMPT=0` stops git from hanging on a
password prompt. Errors become safe messages: timeout → 504, git failure → 502, git missing → 500. Afterwards it reads
the commit SHA and branch with `git rev-parse` ([git.py:37-44](../src/astra_rag/services/sources/git.py#L37-L44)).

**HTTP error mapping** ([errors.py:7-20](../src/astra_rag/services/sources/errors.py#L7-L20)). 401 → "rejected the
token"; 403 and 429 → "denied the request (rate limit or missing permission)"; 404 → "not found / no access"
(or a caller-specific message); 409 → "repository is empty"; anything else → 502; network failure → 502 "Could not
reach". Messages never include the response body or the token.

**Callers switched to the adapter:**

| Caller | Before P2 | After P2 |
|---|---|---|
| `routes.validate_and_clone` | `github_client.list_root` | `adapter_for(...).list_dir("")`. Since P4 this lives in `connections.connect` and lists the tracked branch ([connections.py:40-43](../src/astra_rag/services/connections.py#L40-L43)) |
| `cloner.clone_repo` | built the git command itself | only picks the folder and deletes the old clone, then calls `adapter.clone` ([cloner.py:12-18](../src/astra_rag/services/cloner.py#L12-L18)) |
| `chunker._source_url` | built a GitHub blob link | `adapter_for(repo.ref).citation_url(...)`, pinned to the commit SHA ([chunker.py:61-64](../src/astra_rag/services/ingestion/chunker.py#L61-L64)) |
| `validator.find_missing` | took a GitHub listing | takes the adapter's host-neutral `DirEntry` list ([validator.py:5-11](../src/astra_rag/services/validator.py#L5-L11)) |

**Contract test suite** ([tests/sources/contract.py](../tests/sources/contract.py)). A mixin class, `AdapterContract`,
holds tests that every adapter must pass. Each host's test class supplies `make_adapter` and `stub_*` hooks that script
that host's REST replies on a fake HTTP layer ([fake_http.py](../tests/sources/fake_http.py)), and the clone test uses a
real local bare git repo with two branches. No network and no real token are needed.

### Tests

| Test | What it proves |
|---|---|
| [contract.py:43](../tests/sources/contract.py#L43) `test_list_dir_root_and_subfolder` | Listing works for root and sub-folders. |
| [contract.py:51](../tests/sources/contract.py#L51) `test_read_file_returns_bytes` | File read returns raw bytes. |
| [contract.py:55](../tests/sources/contract.py#L55) `test_head_sha_and_default_branch` | Branch head and default branch. |
| [contract.py:62](../tests/sources/contract.py#L62) `test_is_ancestor_both_ways` | Ancestry true and false. |
| [contract.py:69](../tests/sources/contract.py#L69) `test_citation_url_needs_no_credential_and_marks_lines` | Links work without a token and include lines. |
| [contract.py:79](../tests/sources/contract.py#L79) `test_network_calls_need_a_credential` | No token → clear error. |
| [contract.py:84](../tests/sources/contract.py#L84) `test_http_failures_map_to_safe_app_errors` | 401/403/429/404/409/500 map to the right status ([table at contract.py:18](../tests/sources/contract.py#L18)). |
| [contract.py:96](../tests/sources/contract.py#L96) `test_unreachable_host_is_a_502` | Network failure → 502. |
| [contract.py:111](../tests/sources/contract.py#L111) `test_verify_webhook_is_reserved` | Webhook stub raises 501. |
| [contract.py:116](../tests/sources/contract.py#L116) `test_clone_default_and_explicit_branch_without_leaking_the_token` | Real clone from a local bare repo; token not in `.git/config`. |
| [test_github.py:16](../tests/sources/test_github.py#L16) `GitHubContractTests` | GitHub passes the contract. |
| [test_github.py:45-101](../tests/sources/test_github.py#L45-L101) | GitHub specifics: Enterprise URLs, root listing URL unchanged from before, `ref` query, raw read, `x-access-token` header, blob link, original error messages kept, bad JSON → 502. |
| [test_credentials.py:9-28](../tests/sources/test_credentials.py#L9-L28) | Token never in `repr`/`str`/logs; no `__dict__`. |
| [test_git.py:25-57](../tests/sources/test_git.py#L25-L57) | Header not in argv, symlinks off, explicit branch cloned alone, failures become safe errors. |
| [test_registry.py:11](../tests/sources/test_registry.py#L11), [:15](../tests/sources/test_registry.py#L15) | Every supported kind has an adapter; github/ghe use the GitHub adapter. |
| [test_routes.py:26-33](../tests/test_routes.py#L26-L33) | In P2 the route tests patched `routes.adapter_for` instead of `github_client`, assertions unchanged. Since P4 they patch `services.connections.adapter_for`; since P5 also the sync service's, through one `fake_host` helper ([test_routes.py:22-23](../tests/test_routes.py#L22-L23), [:37](../tests/test_routes.py#L37)). |

### Plan vs delivered

| Plan item | Status |
|---|---|
| `SourceAdapter` with `parse_url`, `list_dir`, `read_file`, `head_sha`, `default_branch`, `clone`, `citation_url`, `is_ancestor`, `verify_webhook` stub | ✅ all nine |
| `Credential` protocol (PAT only) | ✅ |
| Shared error mapping to `AppError` | ✅ |
| Registry picks adapter from URL host | ✅ |
| GitHub logic moved into `sources/github.py` | ✅ (`github_client.py` deleted) |
| Routes, validator, ingestion use the adapter | ✅ |
| `chunker._source_url` uses `citation_url` | ✅ |
| Contract test mixin with fake HTTP + local bare repo | ✅ |
| No behaviour change (requests, headers, messages, JSON bodies) | ✅ per CHANGELOG and GitHub-specific tests that pin the old request and messages |
| Out of scope: new hosts, ETag caching | ✅ respected |

---

## 6. Phase P3: Azure DevOps adapter

**Commit:** `4607ba9` · **Status:** ✅ code and tests done · ⚠️ not yet checked against a real ADO repo

### Goal
The first new host. An Azure DevOps (ADO) golden repo should connect, validate, clone and ingest end to end, and search
results should link back to ADO at the right commit.

### What was delivered
1. [`services/sources/azure_devops.py`](../src/astra_rag/services/sources/azure_devops.py), an adapter that passes the
   same contract suite as GitHub.
2. Registered in `registry.ADAPTERS` and in `config.SUPPORTED_HOST_KINDS`.
3. A shared JSON decoder, [`json_reply.py`](../src/astra_rag/services/sources/json_reply.py), that can treat an HTML
   sign-in page as a rejected token.
4. UI label and placeholder mention Azure DevOps.

### How it works

**URL forms accepted** ([azure_devops.py:25-47](../src/astra_rag/services/sources/azure_devops.py#L25-L47)):

| Form | Example | Result |
|---|---|---|
| Standard | `https://dev.azure.com/acme/proj/_git/golden` | org `acme`, project `proj`, repo `golden` |
| With user prefix | `https://acme@dev.azure.com/acme/proj/_git/golden` | same |
| With extra path / query | `https://dev.azure.com/acme/proj/_git/golden/?path=/x` | same |
| Legacy subdomain | `https://acme.visualstudio.com/proj/_git/golden` | same (org taken from subdomain, [L31-32](../src/astra_rag/services/sources/azure_devops.py#L31-L32)) |
| Legacy with `DefaultCollection` | `https://acme.visualstudio.com/DefaultCollection/proj/_git/golden` | same ([L33-34](../src/astra_rag/services/sources/azure_devops.py#L33-L34)) |
| Project-less shorthand | `https://dev.azure.com/acme/_git/golden` | project = repo name ([L42-43](../src/astra_rag/services/sources/azure_devops.py#L42-L43)) |

- Percent-encoded names (spaces etc.) are decoded on parse and re-encoded when building URLs.
- Names with control characters, `\ / : * ? " < > |`, or that are `.`/`..`, are rejected
  ([L19](../src/astra_rag/services/sources/azure_devops.py#L19), [L44-45](../src/astra_rag/services/sources/azure_devops.py#L44-L45)).
- **All forms normalise to host `dev.azure.com`** ([L47](../src/astra_rag/services/sources/azure_devops.py#L47)), so
  the legacy and new URLs for the same repo share one slug, e.g. `dev.azure.com__acme__proj__golden`, and therefore
  one saved token, clone folder and collection.

**REST calls** (all under `https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}`, `api-version=7.1`,
[L17](../src/astra_rag/services/sources/azure_devops.py#L17), [L58-61](../src/astra_rag/services/sources/azure_devops.py#L58-L61)):

| Method | ADO call | Notes | Lines |
|---|---|---|---|
| `list_dir` | `items?scopePath=/<path>&recursionLevel=OneLevel` | ADO returns the folder itself first; it is dropped. Object types: `tree` → dir, `blob` → file, `commit` → submodule. | [81-95](../src/astra_rag/services/sources/azure_devops.py#L81-L95), types at [L21](../src/astra_rag/services/sources/azure_devops.py#L21) |
| `read_file` | `items?path=/<path>&$format=octetStream&download=true` | Raw bytes. | [97-100](../src/astra_rag/services/sources/azure_devops.py#L97-L100) |
| `head_sha` | `refs?filter=heads/<branch>` | ADO's filter is a **prefix** match (`main` also matches `main-old`), so the code looks for the exact `refs/heads/<branch>`. | [102-108](../src/astra_rag/services/sources/azure_devops.py#L102-L108) |
| `default_branch` | repository info → `defaultBranch` | Missing → 409 "repository is empty". `refs/heads/` prefix stripped. | [110-117](../src/astra_rag/services/sources/azure_devops.py#L110-L117) |
| `is_ancestor` | `diffs/commits?baseVersion=…&targetVersion=…` | `behindCount == 0` means `head` contains `base`. | [119-124](../src/astra_rag/services/sources/azure_devops.py#L119-L124) |
| version selection | `versionDescriptor.version` + `versionType` | A 40- or 64-hex string is treated as a commit, anything else as a branch. | [69-75](../src/astra_rag/services/sources/azure_devops.py#L69-L75) |

**Auth** ([L63-67](../src/astra_rag/services/sources/azure_devops.py#L63-L67)). `Authorization: Basic base64(":<PAT>")`
(empty user name), for both REST calls and the git clone header
([L126-127](../src/astra_rag/services/sources/azure_devops.py#L126-L127)). The clone goes through the same shared
`git_clone` as GitHub, so the env-var header and `core.symlinks=false` rules apply.

**Sign-in page = rejected token** ([L77-79](../src/astra_rag/services/sources/azure_devops.py#L77-L79),
[json_reply.py:8-15](../src/astra_rag/services/sources/json_reply.py#L8-L15)). With an invalid or expired PAT, ADO
often replies **203 with an HTML sign-in page** instead of a 401. The adapter checks whether the body starts with `<`
and, if so, raises the same 401 "rejected the token" error. `http.get_json` was changed to use the shared
`parse_json` too ([http.py:21-22](../src/astra_rag/services/sources/http.py#L21-L22)).

**Citation link** ([L129-134](../src/astra_rag/services/sources/azure_devops.py#L129-L134)).
`https://dev.azure.com/{org}/{project}/_git/{repo}?path=/<path>&version=GC<sha>` for a commit (`GB<branch>` for a branch).
With lines: `&line=<start>&lineEnd=<end+1>&lineStartColumn=1&lineEndColumn=1`. ADO's end position is exclusive, so
the code points at column 1 of the line after the range. This differs slightly from the plan text (`&line=&lineEnd=`)
and has not been checked in a real browser yet.

**Case-sensitivity of required names** (plan open question). ADO looks paths up case-insensitively, but our
validator compares the **names ADO lists** against `config.REQUIRED_FILES/FOLDERS` exactly, so `Policies.md` still
counts as missing `policies.md`. Enforced by [test_azure_devops.py:170](../tests/sources/test_azure_devops.py#L170).
What ADO itself does with case on a real repo is still unconfirmed.

**UI** ([index.html:18-19](../src/astra_rag/templates/index.html#L18-L19)): label "Repository URL (GitHub or Azure
DevOps)" and a placeholder showing both URL shapes.

### Where

| What | File and lines |
|---|---|
| Adapter | [azure_devops.py](../src/astra_rag/services/sources/azure_devops.py) (147 lines) |
| Registration | [registry.py:9](../src/astra_rag/services/sources/registry.py#L9), [registry.py:12-14](../src/astra_rag/services/sources/registry.py#L12-L14), [config.py:16](../src/astra_rag/config.py#L16) |
| Host detection (`dev.azure.com`, `*.visualstudio.com`) | [repo_ref.py:29-30](../src/astra_rag/services/repo_ref.py#L29-L30) |
| Shared JSON / sign-in page handling | [json_reply.py](../src/astra_rag/services/sources/json_reply.py) |
| UI text | [index.html:18-19](../src/astra_rag/templates/index.html#L18-L19) |

### Tests

| Test | What it proves |
|---|---|
| [test_azure_devops.py:18-41](../tests/sources/test_azure_devops.py#L18-L41) `AzureDevOpsContractTests` | ADO passes the full contract suite (stubs mimic real ADO reply shapes, including the folder-first listing and prefix-matched refs). |
| [test_azure_devops.py:45](../tests/sources/test_azure_devops.py#L45) `test_all_accepted_forms_give_the_same_repo` | Five URL forms → same `RepoRef` and slug. |
| [test_azure_devops.py:64](../tests/sources/test_azure_devops.py#L64) `test_shorthand_uses_the_repo_name_as_the_project` | Project-less forms. |
| [test_azure_devops.py:69](../tests/sources/test_azure_devops.py#L69) `test_encoded_names_are_decoded_and_re_encoded` | Spaces in names round-trip. |
| [test_azure_devops.py:75](../tests/sources/test_azure_devops.py#L75) `test_bad_shapes_are_rejected` | Missing `_git`, too many segments, `..`, `:` etc. rejected. |
| [test_azure_devops.py:90](../tests/sources/test_azure_devops.py#L90) `test_requests_use_basic_auth_with_an_empty_user` | Header is `Basic base64(":token")`. |
| [test_azure_devops.py:97](../tests/sources/test_azure_devops.py#L97) `test_query_parameters` | `api-version`, version descriptors, encoding. |
| [test_azure_devops.py:110](../tests/sources/test_azure_devops.py#L110) `test_list_dir_drops_the_folder_itself_and_reports_object_types` | Folder-itself row dropped; submodules reported. |
| [test_azure_devops.py:121](../tests/sources/test_azure_devops.py#L121) `test_read_file_asks_for_the_raw_body_and_encodes_spaces` | Raw download, `%20` not `+`. |
| [test_azure_devops.py:129](../tests/sources/test_azure_devops.py#L129) `test_head_sha_needs_an_exact_branch_match` | Prefix-match trap handled. |
| [test_azure_devops.py:135](../tests/sources/test_azure_devops.py#L135) `test_empty_repo_has_no_default_branch` | Empty repo → 409. |
| [test_azure_devops.py:141](../tests/sources/test_azure_devops.py#L141) `test_a_sign_in_page_means_the_token_was_rejected` | 203 + HTML → 401. |
| [test_azure_devops.py:149](../tests/sources/test_azure_devops.py#L149) `test_unexpected_reply_shapes_are_a_502` | Bad JSON shapes → safe 502. |
| [test_azure_devops.py:157](../tests/sources/test_azure_devops.py#L157) `test_clone_uses_the_basic_header_and_the_repo_url` | Clone URL and header. |
| [test_azure_devops.py:164](../tests/sources/test_azure_devops.py#L164) `test_citation_url_pins_a_commit_or_a_branch` | `GC<sha>` vs `GB<branch>`, line range format. |
| [test_azure_devops.py:170](../tests/sources/test_azure_devops.py#L170) `test_required_root_names_stay_case_sensitive` | `Policies.md` does not satisfy `policies.md`. |
| [test_registry.py:21](../tests/sources/test_registry.py#L21) `test_azure_devops_uses_its_own_adapter` | Registry dispatch. |

### Plan vs delivered

| Plan item | Status |
|---|---|
| URLs: `dev.azure.com/{org}/{project}/_git/{repo}` and legacy `{org}.visualstudio.com/...` | ✅ plus `DefaultCollection`, `org@` and shorthand forms |
| REST: repo info with `defaultBranch` | ✅ |
| REST: `items` with `recursionLevel=OneLevel` to list | ✅ |
| REST: `items?path=&versionDescriptor` to read | ✅ |
| REST: `refs?filter=heads/` for branch head | ✅ (exact-match fix included) |
| Auth: Basic with empty user, REST and git header | ✅ |
| Citation URL `?path=&version=GC{sha}&line=&lineEnd=` | ✅ in code ⚠️ exclusive-end format not checked in a browser |
| Confirm ADO case-sensitivity; enforce exact case ourselves | ✅ exact case enforced ⚠️ real ADO behaviour not confirmed |
| UI placeholder and help text mention ADO | ✅ |
| Tests: contract suite with faked ADO replies | ✅ |
| Tests: both URL forms | ✅ |
| Tests: errors for 401, 403, 404 and "repo not found" | ✅ via contract suite + sign-in page case |
| Out of scope: ADO service hooks | ✅ respected |
| **Acceptance: connect a real ADO golden repo, validate, clone, ingest, links point at the right commit** | ❌ **not done yet** (recorded as open in TASKS.md and CHANGELOG) |

---

## 7. Phase P4: Repo registry, project bindings and tracked branch

**Commit:** `36cd57c` · **Status:** ✅ code and tests done · ⚠️ manual acceptance with a real repo not run yet

### Goal
Move repo state out of memory and into a proper store, bind ASTRA projects to a golden repo, and make the tracked
branch configurable (plan §D1, §D6). Before P4 the ingestion status lived in a Python dict (lost on restart), there
was no list of repos, and every clone took the host's default branch.

### What was delivered
1. **A SQLite registry**, [`services/registry/`](../src/astra_rag/services/registry/), at `data/astra.db` (git-ignored,
   override with `ASTRA_DB_PATH`). All registry SQL lives in this package.
2. **Three tables:** `repos`, `project_bindings`, `ingestion_runs`, created by a versioned migration.
3. **Tracked branch:** set at connect time (blank = the saved branch, else the host's default), changeable later with
   `PUT /api/repos/{slug}/settings`. The clone uses `--branch <tracked> --single-branch`.
4. **Persistent status:** ingestion progress is written to the run row; `GET /api/ingestion-status/{slug}` reads it,
   so it survives a restart. Runs a previous process left active are swept to `failed` at startup.
5. **Configured vs indexed:** each repo keeps its configured branch separately from the last good build, plus a derived
   `needs_rebuild` and an `index_state` (`rebuilding` / `none` / `incomplete` / `ready`).
6. **One active run per repo:** a second connect while a run is queued or running gets 409, checked atomically.
   *Since P5:* still one active run per repo, but a later request becomes one follow-up run instead of a 409.
7. **Cleaned URLs:** the stored URL (registry and `.env`) is rebuilt from the `RepoRef` (new `SourceAdapter.web_url`).
8. **New APIs:** `GET /api/repos`, `PUT /api/repos/{slug}/settings`, `PUT /api/projects/{project_id}/binding`,
   `GET /api/projects/{project_id}`.
9. **UI:** a branch field on the connect form and a "Connected repositories" table.
10. **Refactor:** the connect logic moved from `routes.py` into
    [`services/connections.py`](../src/astra_rag/services/connections.py), so routes stay thin.

### How it works

**Schema** ([db.py:12-65](../src/astra_rag/services/registry/db.py#L12-L65)):

| Table | Key columns | Notes |
|---|---|---|
| `repos` | `slug` PK, `url` (cleaned), `host_kind`, `host`, `tracked_branch`, `config_version`, `credential_ref`, `indexed_run_id`, `indexed_branch`, `indexed_commit_sha`, `indexed_collection`, `indexed_config_version`, `indexed_at` | `credential_ref` is the **name** of the `.env` key (e.g. `env:ASTRA_REPO_..._TOKEN`, [token_store.py:106-108](../src/astra_rag/services/token_store.py#L106-L108)), never the token. |
| `project_bindings` | `project_id` PK → `repo_slug` (FK to `repos`) | The primary key makes "one repo per project" a database rule. A repo can serve many projects. |
| `ingestion_runs` | `id`, `repo_slug` (FK), `state` (CHECK: queued/running/done/failed), `branch`, `config_version`, `commit_sha`, `collection`, `index_replaced`, counts, `files_skipped`/`warnings` (JSON), `error`, timestamps | One row per connect. The latest row is the status. |

**Connections and migrations** ([db.py:90-118](../src/astra_rag/services/registry/db.py#L90-L118)):
- Every connection turns on `PRAGMA foreign_keys` and a 5 s `busy_timeout`; the database uses WAL so status reads do
  not block the ingestion writer ([db.py:95-96](../src/astra_rag/services/registry/db.py#L95-L96), [:103](../src/astra_rag/services/registry/db.py#L103)).
- `MIGRATIONS` is an ordered list; entry *i* upgrades schema version *i* to *i+1*. `migrate()` runs inside one
  `BEGIN IMMEDIATE` transaction, applies each missing entry and bumps `PRAGMA user_version` with it. Any error rolls
  everything back. A database whose version is **newer** than the code is refused with an error and left untouched
  ([db.py:107-109](../src/astra_rag/services/registry/db.py#L107-L109)); it is never downgraded.
- The first use in a process migrates lazily ([db.py:121-125](../src/astra_rag/services/registry/db.py#L121-L125)); the
  app lifespan also runs it at startup.
- `transaction()` gives one connection and one transaction; writes start with `BEGIN IMMEDIATE`, so a check followed by
  an insert cannot interleave with another request ([db.py:128-143](../src/astra_rag/services/registry/db.py#L128-L143)).

**Tracked branch** ([connections.py:35-40](../src/astra_rag/services/connections.py#L35-L40)):
- A typed branch is checked against `config.BRANCH_NAME_PATTERN` ([config.py:25](../src/astra_rag/config.py#L25)) before
  any host call: no leading `-` or `/` or `.`, no `..`, `//` or `/.`, no trailing `/`, `.` or `.lock`, only
  `[A-Za-z0-9._/-]`, at most 200 characters. This also stops a branch name being read as a git option.
- Blank means the repo's saved tracked branch, else `adapter.default_branch()`.
- `adapter.head_sha(branch)` gives a clear 404 if it does not exist; the root is then listed at that branch.
- `PUT /api/repos/{slug}/settings` ([connections.change_branch](../src/astra_rag/services/connections.py#L51-L65)) checks
  the name, uses the **saved** token to confirm the branch exists, then
  [`repos.set_tracked_branch`](../src/astra_rag/services/registry/repos.py#L27-L33) updates it and bumps `config_version`.
  Setting the same branch is a no-op. Nothing rebuilt by itself in P4 (the next connect did it); *since P5* a real
  change starts a forced rebuild straight away ([connections.py:64](../src/astra_rag/services/connections.py#L64)).

**Configured vs indexed** ([runs.finish_run](../src/astra_rag/services/registry/runs.py#L83-L95), [repos._view](../src/astra_rag/services/registry/repos.py#L92-L114)):
- Each run records the `branch` and `config_version` it was queued with ([runs.py:54-57](../src/astra_rag/services/registry/runs.py#L54-L57)).
- Only a run that finishes `done` writes the repo's `indexed_*` fields, and only if its id is newer than the current
  `indexed_run_id` ([runs._promote](../src/astra_rag/services/registry/runs.py#L107-L113)). A failed run (clone or
  ingestion) never touches them, so they always describe the last good build.
- `needs_rebuild` is **derived**, not stored: true if the index state is `none` or `incomplete`, or if
  `indexed_config_version != config_version`. A branch change during a run therefore stays pending after that run
  succeeds, and there is no flag for an old run to clear by mistake.
- `index_state` ([repos._index_state](../src/astra_rag/services/registry/repos.py#L132-L141)):

| State | When |
|---|---|
| `rebuilding` | the latest run is queued or running |
| `none` | the repo has never had a successful run |
| `incomplete` | a run after the last good one dropped the Qdrant collection (`index_replaced = 1`, set just before `store.recreate`; see `git show 36cd57c:src/astra_rag/services/ingestion/pipeline.py`) and did not finish `done`: search may be empty or partial. *Since P5* no run drops the live index, so only runs from before P5 can cause this state. |
| `ready` | otherwise (a failure before Qdrant was touched, e.g. a clone failure, leaves the old index serving) |

**One active run per repo** (P4: `runs.queue_run`, see `git show 36cd57c:src/astra_rag/services/registry/runs.py`). In
one `BEGIN IMMEDIATE` transaction: if the repo had a `queued` or `running` run, raise 409 and change nothing; otherwise
insert or update the repo row (a new branch adds 1 to `config_version`) and insert the `queued` run. The run was created
**before** cloning, so a clone failure was recorded as a failed run.
*Since P5* the same transaction lives in [runs.register_and_queue](../src/astra_rag/services/registry/runs.py#L15-L34)
(the `config_version` rule is at [runs.py:31](../src/astra_rag/services/registry/runs.py#L31)) and
[runs._queue](../src/astra_rag/services/registry/runs.py#L46-L60), which folds a request into a follow-up instead of
raising 409; the clone runs in the sync worker ([service._build](../src/astra_rag/services/sync/service.py#L55-L69)).

**Run progress** ([runs.update_run](../src/astra_rag/services/registry/runs.py#L73-L80), [pipeline.py:34-102](../src/astra_rag/services/ingestion/pipeline.py#L34-L102)).
The pipeline writes `running`, then the counts after loading, before the collection is dropped (*since P5:* when the
new version collection is created), and after every embed batch. Updates only apply while a run is still active, so a late write cannot revive a finished or swept run. Column
names come only from a fixed allow-list ([runs.py:116-122](../src/astra_rag/services/registry/runs.py#L116-L122)); values are
always bound parameters.

**Restart** ([registry.startup](../src/astra_rag/services/registry/__init__.py#L6-L9), [runs.sweep_interrupted](../src/astra_rag/services/registry/runs.py#L139-L144)).
Nothing can still be running when the process starts, so any `queued`/`running` run is marked `failed` with
"Interrupted by a server restart." This also stops a crash from blocking a repo for good (with a 409 in P4, with
follow-ups that never start since P5).

**Cleaned URLs** ([base.py:42-45](../src/astra_rag/services/sources/base.py#L42-L45), [github.py:30-32](../src/astra_rag/services/sources/github.py#L30-L32), [azure_devops.py:49-52](../src/astra_rag/services/sources/azure_devops.py#L49-L52)).
`web_url` is built from the `RepoRef`, so userinfo (`user:pass@`), query strings and fragments the user typed are never
stored. Both the registry and `token_store.save` get this URL ([connections.py:42](../src/astra_rag/services/connections.py#L42), [:47](../src/astra_rag/services/connections.py#L47)).

**APIs** ([routes.py:49-102](../src/astra_rag/routes.py#L49-L102)). The repo view never includes the token or
`credential_ref` ([repos.py:92-114](../src/astra_rag/services/registry/repos.py#L92-L114)). Project ids must match
`config.PROJECT_ID_PATTERN` ([config.py:26](../src/astra_rag/config.py#L26), [rules.py:16-19](../src/astra_rag/services/registry/rules.py#L16-L19)).
Rebinding a project is one `INSERT ... ON CONFLICT DO UPDATE` statement; an unknown repo trips the foreign key, which
becomes a 404, and the old binding stays ([repos.py:71-80](../src/astra_rag/services/registry/repos.py#L71-L80)).

**UI** ([index.html:25-28](../src/astra_rag/templates/index.html#L25-L28), [index.html:36-43](../src/astra_rag/templates/index.html#L36-L43), [app.js:9-75](../src/astra_rag/static/app.js#L9-L75)).
A "Branch to track" field, and a table of repos with tracked branch, indexed `branch @ sha`, state, and a "rebuild
pending: reconnect" badge. The last failed run's error shows as a tooltip on the state. *Since P5* the table shows the
sync status, the last check and a Sync now button instead (see §8).

### Where

| What | File and lines |
|---|---|
| Connect flow and branch change | [connections.py](../src/astra_rag/services/connections.py) (77 lines) |
| Connections, transactions, migrations | [registry/db.py](../src/astra_rag/services/registry/db.py) |
| Repos, bindings, repo view, `index_state` | [registry/repos.py](../src/astra_rag/services/registry/repos.py) |
| Runs: queue (409 in P4, coalescing since P5), progress, finish, sweep | [registry/runs.py](../src/astra_rag/services/registry/runs.py) |
| Branch name and project id checks | [registry/rules.py](../src/astra_rag/services/registry/rules.py), [config.py:21-26](../src/astra_rag/config.py#L21-L26) |
| Startup (migrate + sweep) | [registry/\_\_init\_\_.py](../src/astra_rag/services/registry/__init__.py), [`__init__.py:15-30`](../src/astra_rag/__init__.py#L15-L30) |
| Pipeline writing to runs | [pipeline.py:34-102](../src/astra_rag/services/ingestion/pipeline.py#L34-L102) |
| `web_url` on the port and adapters | [base.py:42-45](../src/astra_rag/services/sources/base.py#L42-L45), [github.py:30-32](../src/astra_rag/services/sources/github.py#L30-L32), [azure_devops.py:49-52](../src/astra_rag/services/sources/azure_devops.py#L49-L52) |
| `credential_ref` | [token_store.py:106-108](../src/astra_rag/services/token_store.py#L106-L108) |
| Routes | [routes.py:18-30](../src/astra_rag/routes.py#L18-L30) (bodies), [routes.py:49-102](../src/astra_rag/routes.py#L49-L102) |
| `data/` git-ignored | [.gitignore](../.gitignore) |

### Tests

| Test | What it proves |
|---|---|
| [test_registry.py:34](../tests/test_registry.py#L34) `test_fresh_database_gets_the_current_schema_and_rerunning_is_harmless` | Migration creates the tables; running it twice is harmless. |
| [test_registry.py:40](../tests/test_registry.py#L40) `test_a_newer_database_is_refused_and_left_untouched` | Schema 99 → error, version stays 99. |
| [test_registry.py:49](../tests/test_registry.py#L49) `test_a_failing_migration_rolls_back_completely` | A broken extra migration leaves the previous version and no half-made table. |
| [test_registry.py:57](../tests/test_registry.py#L57) `test_the_first_use_migrates_lazily` | No explicit migrate needed. |
| [test_registry.py:78](../tests/test_registry.py#L78) `test_foreign_keys_are_enforced_on_every_connection` | A binding to an unknown repo is rejected by SQLite. |
| [test_registry.py:87](../tests/test_registry.py#L87), [:96](../tests/test_registry.py#L96) | Repo registered without the token; `set_tracked_branch` bumps the version only on a real change; 404 for unknown. |
| [test_registry.py:107](../tests/test_registry.py#L107) `test_one_repo_per_project_and_one_repo_serves_many_projects` | Binding rules from the plan. |
| [test_registry.py:118](../tests/test_registry.py#L118) `test_a_failed_rebind_keeps_the_old_binding` | Rebinding to an unknown repo → 404, old binding kept. |
| [test_registry.py:131](../tests/test_registry.py#L131) `test_done_run_becomes_the_indexed_build` | `indexed_*`, `ready`, JSON fields round-trip. |
| [test_registry.py:144](../tests/test_registry.py#L144) `test_a_failed_run_never_overwrites_the_last_good_build` | Failure before Qdrant → `ready`; after dropping the collection → `incomplete`; a later clone failure keeps `incomplete`. |
| [test_registry.py:168](../tests/test_registry.py#L168) `test_branch_change_during_a_run_keeps_needs_rebuild_after_it_succeeds` | Configured `dev`, indexed `main`, `needs_rebuild` true. |
| [test_registry.py:176](../tests/test_registry.py#L176) `test_an_older_run_finishing_late_does_not_replace_a_newer_build` | Run-id ordering guard. |
| [test_registry.py:187](../tests/test_registry.py#L187), [:197](../tests/test_registry.py#L197) | Sweep at startup; swept runs ignore late updates and finishes. |
| [test_registry.py:203](../tests/test_registry.py#L203) `test_one_active_run_per_repo_and_later_triggers_coalesce` (was `test_one_active_run_per_repo`, 409, before P5) | One run while active, later requests become one pending follow-up; other repos not blocked. |
| [test_registry.py:271](../tests/test_registry.py#L271) `test_concurrent_queues_start_exactly_one_run` | 8 threads at once → exactly 1 run; the other 7 become one pending follow-up (7 × 409 before P5). |
| [test_registry.py:289](../tests/test_registry.py#L289) `test_unknown_run_fields_are_rejected` | Column allow-list; only final states accepted by `finish_run`. |
| [test_registry.py:298](../tests/test_registry.py#L298), [:306](../tests/test_registry.py#L306) | Branch name and project id rules (valid and invalid cases). |
| [test_routes.py:76](../tests/test_routes.py#L76) `test_connect_queues_a_background_sync_on_the_default_branch` (was `test_clone_queues_a_persisted_run_on_the_default_branch` before P5) | Default branch used for `head_sha`, `list_dir` and clone; run persisted; cleaned URL saved. |
| [test_routes.py:98](../tests/test_routes.py#L98), [:106](../tests/test_routes.py#L106) | Explicit branch tracked; blank branch keeps the saved one. |
| [test_routes.py:113](../tests/test_routes.py#L113), [:121](../tests/test_routes.py#L121) | Unknown branch → 404, nothing registered; option-like branch names rejected before any host call. |
| [test_routes.py:140](../tests/test_routes.py#L140), [:150](../tests/test_routes.py#L150) | Clone failures (expected and unexpected) are failed runs; the last good index is kept; the exception text never leaks (since P5 the clone is in the background, so the request itself succeeds). |
| [test_routes.py:169](../tests/test_routes.py#L169) | 422 registers and queues nothing. |
| [test_routes.py:178](../tests/test_routes.py#L178) `test_second_connect_while_a_run_is_active_becomes_one_follow_up` (was `..._is_409_and_does_not_clone` before P5) | No second clone; the request becomes `pending` and the follow-up clones the new branch. |
| [test_routes.py:194](../tests/test_routes.py#L194), [:205](../tests/test_routes.py#L205) | Credentials, query and fragment are not stored or echoed; bad-URL errors do not echo the URL. |
| [test_routes.py:232](../tests/test_routes.py#L232) `test_repo_list_never_contains_the_token_or_its_location` | No token, `credential_ref`, `env:` or `_TOKEN` in `GET /api/repos`. |
| [test_routes.py:239](../tests/test_routes.py#L239) `test_changing_the_branch_starts_a_rebuild_from_it` (was `..._marks_a_rebuild_and_the_next_connect_uses_it` before P5) | The plan's acceptance flow, end to end with fakes; since P5 the rebuild starts at once. |
| [test_routes.py:258](../tests/test_routes.py#L258), [:266](../tests/test_routes.py#L266) | Same branch is a no-op; settings errors (unregistered, no saved token, missing branch, bad name). |
| [test_routes.py:278](../tests/test_routes.py#L278) `test_project_binding_routes` | Bind, read, failed rebind keeps the old one, unbound 404, bad id 422. |
| [test_routes.py:292](../tests/test_routes.py#L292) `test_repos_and_status_survive_a_restart` | A fresh app on the same database: repo list kept, interrupted run swept, new connect allowed. |
| [test_ingestion.py:383](../tests/test_ingestion.py#L383) `test_failure_mid_rebuild_keeps_the_old_index_serving` (was `..._flags_the_index` before P5) | Embedder crash → failed run, last good build kept; since P5 the index stays `ready` and keeps serving. |
| [test_ingestion.py:401](../tests/test_ingestion.py#L401) `test_done_run_records_the_indexed_commit` | Pipeline success updates `indexed_*`. |
| [contract.py:116](../tests/sources/contract.py#L116), single-branch check at [:130-132](../tests/sources/contract.py#L130-L132) | Clone of `dev` from a local bare repo with two branches contains only `origin/dev`. |
| [contract.py:104](../tests/sources/contract.py#L104), [test_github.py:52](../tests/sources/test_github.py#L52), [test_azure_devops.py:57](../tests/sources/test_azure_devops.py#L57) | `web_url` is canonical HTTPS without userinfo, query or fragment, for each host. |
| [tests/\_\_init\_\_.py](../tests/__init__.py), [tests/helpers.py](../tests/helpers.py) | Every suite uses a temporary database; `ASTRA_DB_PATH` points at a temp file as a safety net, so tests never touch `data/`. |

### Plan vs delivered

| Plan item ([phases.md P4](../plan/phases.md)) | Status |
|---|---|
| `services/registry/` SQLite store at `data/astra.db`, git-ignored | ✅ plus `ASTRA_DB_PATH` override |
| `repos (slug, url, host_kind, tracked_branch, created_at)` | ✅ plus host, `config_version`, `credential_ref`, `indexed_*`, `updated_at` |
| `project_bindings` (one repo per project) | ✅ enforced by the primary key and a foreign key |
| `ingestion_runs` (persisted status) | ✅ |
| Tokens stay in `.env`; registry stores only a credential reference | ✅ `credential_ref` = key name |
| Tracked branch defaults to the host default, set at connect, changeable later | ✅ |
| A branch change marks the repo for a full rebuild | ✅ derived `needs_rebuild`; in P4 the rebuild happened at the next connect, since P5 it starts at once |
| Clone uses `--branch <tracked> --single-branch` | ✅ |
| `GET /api/repos`, `PUT /api/repos/{slug}/settings`, `PUT /api/projects/{id}/binding`, `GET /api/projects/{id}` | ✅ |
| `GET /api/ingestion-status` reads from the store, survives restart | ✅ |
| UI: branch field, repos list with branch, last commit and state | ✅ |
| Tests: store CRUD on a temp DB; binding rules; clone of the tracked branch on a two-branch bare repo | ✅ |
| Out of scope: scheduled sync (P5), API auth | ✅ respected |
| Added during plan review (not in phases.md): FK on every connection, migration safety, configured vs indexed build, failure recording, atomic 409 guard (replaced by coalescing in P5), run-id ordering, cleaned URLs | ✅ |
| **Acceptance: restart keeps the repo list and last status; a branch change is used by the next ingest** | ⚠️ checked on the real server with a seeded scratch database (restart kept the repo, the binding and "configured `dev` · indexed `main`", and swept the interrupted run). **Not yet run with a real repo and PAT.** |

---

## 8. Phase P5: Sync (nightly and Sync now) with alias swap

**Commit:** not committed yet (working tree on `goldan-repo-re-guru`) · **Status:** ✅ code and tests done · ⚠️ manual acceptance with a real repo and Qdrant not run yet

### Goal
Keep each repo's index on the latest commit of its tracked branch, and never leave search empty while that happens
(plan §D7, §E2). Before P5 a rebuild dropped the live Qdrant collection first (search empty during a rebuild, partial
after a failed one), nothing rebuilt by itself, and a second connect during a run got 409.

**Constraint agreed for P5: no setup on the customer side.** The server only uses what it already has: the repo URL
and the read-only PAT. No webhooks, apps or CI steps.

### What was delivered
1. **Atomic index replacement.** Each build goes into a new collection `astra_v<run id>__<slug>`; after a point-count
   check the repo's alias `astra__<slug>` is switched to it in one Qdrant call and older versions are dropped. Search
   always reads the alias.
2. **`services/sync/`**, a new package: the sync service (head check, queue, clone, ingest, follow-up), a one-thread
   background worker, a nightly scheduler with a startup catch-up, a startup index recovery, and a single-instance lock.
3. **Triggers:** connect (forced), **Sync now** (`POST /api/repos/{slug}/sync`), a branch change (forced), the nightly
   check at `ASTRA_SYNC_DAILY_AT` (default 02:00 UTC) and the startup catch-up.
4. **Skip when unchanged:** a non-forced sync first asks the host for the branch head; if it equals the indexed commit
   and the configuration did not change, nothing runs and no run row is written.
5. **Coalescing instead of 409:** a request that arrives while a run is active becomes one follow-up run.
6. **Connect goes through the background sync.** The request no longer clones; the response drops `path`, and
   `commit_sha` is the head seen while connecting.
7. **Source errors:** a failed head check or clone (for example a revoked token) is recorded on the repo as
   `source_error`; the old index keeps serving.
8. **Freshness in API and UI:** `sync_status`, last check, indexed commit and time, and the next nightly check.
9. **Hardening from the plan review:** `config_version` changes only with the tracked branch; one instance per data
   directory (enforced); recovery from a crash in the middle of the alias switch; safe-only messages in logs and errors.
10. **Registry schema 2** (one new migration).

### How it works

**Versioned collections behind an alias** ([store.py:21-37](../src/astra_rag/services/ingestion/store.py#L21-L37), [store.py:77-110](../src/astra_rag/services/ingestion/store.py#L77-L110)):

| Piece | What it does | Where |
|---|---|---|
| `collection_name(slug)` | Now the **alias** name (`astra__<slug>`), so search did not change. | [store.py:21-23](../src/astra_rag/services/ingestion/store.py#L21-L23) |
| `version_name(slug, run_id)` | `astra_v<run id>__<slug>`. The run id is unique and increasing, so no extra counter is needed. The plan said `<slug>__v<n>`; that was changed because a repo whose own name ends in `__v3` could have been mistaken for another repo's version. | [store.py:26-28](../src/astra_rag/services/ingestion/store.py#L26-L28) |
| `version_run_id(slug, name)` | Reads the run id back, only for this repo's exact slug. | [store.py:31-36](../src/astra_rag/services/ingestion/store.py#L31-L36) |
| `create` | Creates the new version (replaces P4's drop-and-recreate `recreate`). | [store.py:53-61](../src/astra_rag/services/ingestion/store.py#L53-L61) |
| `swap_alias` | If a pre-P5 real collection still has the alias name, deletes it first (a one-off gap of milliseconds); then sends "delete alias (if any) + create alias" as **one** `update_collection_aliases` call. | [store.py:84-94](../src/astra_rag/services/ingestion/store.py#L84-L94) |
| `delete_version` | The only way a version is deleted: refuses names that are not this repo's versions and **re-reads the alias target first, never deleting the live one**. | [store.py:99-106](../src/astra_rag/services/ingestion/store.py#L99-L106) |
| `drop_versions` | Deletes every other version (old builds, half-built leftovers) through `delete_version`. | [store.py:108-110](../src/astra_rag/services/ingestion/store.py#L108-L110) |

**Pipeline** ([pipeline.py:34-102](../src/astra_rag/services/ingestion/pipeline.py#L34-L102)):
1. Builds into `version_name(slug, run_id)` and records that name on the run ([pipeline.py:80-82](../src/astra_rag/services/ingestion/pipeline.py#L80-L82)).
2. After the upserts, compares `store.count(version)` with the number of chunks; a shortfall fails the run with "Index
   check failed" ([pipeline.py:95-97](../src/astra_rag/services/ingestion/pipeline.py#L95-L97)).
3. Switches the alias, then drops older versions; a failure to drop is only a warning ([pipeline.py:98-102](../src/astra_rag/services/ingestion/pipeline.py#L98-L102)).
4. On any failure, deletes its own half-built version (best effort) and the alias keeps serving the last good one
   ([pipeline.py:48-52](../src/astra_rag/services/ingestion/pipeline.py#L48-L52)).

**Sync service** ([service.py](../src/astra_rag/services/sync/service.py)):

| Function | What it does | Where |
|---|---|---|
| `request_sync(slug, triggered_by, force)` | 404 if the repo is unknown. Unless forced or a run is active, checks the head; unchanged head and no config change → `up_to_date`. Otherwise queues a run (`queued`) or folds the request into a follow-up (`pending`). | [service.py:18-36](../src/astra_rag/services/sync/service.py#L18-L36) |
| `_check_head` | Calls `adapter.head_sha(tracked_branch)` with the saved token; records the check time, or the error as `source_error`, then re-raises. | [service.py:83-92](../src/astra_rag/services/sync/service.py#L83-L92) |
| `execute(run_id)` | Runs in the worker: `_build`, then `_follow_up`. | [service.py:43-52](../src/astra_rag/services/sync/service.py#L43-L52) |
| `_build` | Clone (failure → failed run + `source_error`), commit SHA on the run, then `pipeline.run_ingestion`. | [service.py:55-69](../src/astra_rag/services/sync/service.py#L55-L69) |
| `_follow_up` | Takes the folded-in request (`take_pending`) and starts it. | [service.py:72-80](../src/astra_rag/services/sync/service.py#L72-L80) |
| `_adapter`, `_source_message` | Saved token → adapter (missing token → "Reconnect it with a PAT"); a 401 becomes "Reconnect this repository with a new PAT". | [service.py:95-104](../src/astra_rag/services/sync/service.py#L95-L104) |

**The run row is the per-repo lock** ([runs.py:15-70](../src/astra_rag/services/registry/runs.py#L15-L70)):
- [`register_and_queue`](../src/astra_rag/services/registry/runs.py#L15-L34) is used only by connect: it inserts or updates the repo, clears
  `source_error`, and queues a forced run in the same `BEGIN IMMEDIATE` transaction. It is, together with
  `repos.set_tracked_branch`, the only code that can bump `config_version`, and only when the branch really changes.
- [`queue_run`](../src/astra_rag/services/registry/runs.py#L37-L43) is used by every other trigger. It never touches `config_version` or
  `tracked_branch`, so forced and nightly syncs can't leave `needs_rebuild` stuck on.
- [`_queue`](../src/astra_rag/services/registry/runs.py#L46-L60): if a run is active, sets `sync_pending = 1` and `sync_force = max(sync_force, force)`
  and returns `None`; otherwise inserts the run (with `triggered_by`) and clears any waiting follow-up, because a new
  run rebuilds from scratch anyway.
- [`take_pending`](../src/astra_rag/services/registry/runs.py#L63-L70) reads and clears the follow-up in one transaction.

**Worker** ([worker.py](../src/astra_rag/services/sync/worker.py)): a `ThreadPoolExecutor` with one thread (`SYNC_WORKERS`), started and stopped
by the app lifespan. When it has not been started (tests, scripts) `submit` runs the task inline, so nothing hangs. A
task that raises is logged by exception type only ([worker.py:37-41](../src/astra_rag/services/sync/worker.py#L37-L41)).

**Nightly scheduler** ([scheduler.py](../src/astra_rag/services/sync/scheduler.py)):
- `next_run_at(now, "HH:MM")` is a pure function (UTC); a bad `ASTRA_SYNC_DAILY_AT` fails at startup, not at night
  ([scheduler.py:18-29](../src/astra_rag/services/sync/scheduler.py#L18-L29), [:39-44](../src/astra_rag/services/sync/scheduler.py#L39-L44)).
- The daemon thread first runs a **catch-up** for repos not checked for `SYNC_CATCHUP_HOURS` (24) or waiting for a
  follow-up, then sleeps until the next run time; each night it runs recovery and checks every repo
  ([scheduler.py:55-59](../src/astra_rag/services/sync/scheduler.py#L55-L59)).
- `run_pass` checks repos one by one; one repo's failure is logged and recorded on that repo and never stops the
  others ([scheduler.py:67-78](../src/astra_rag/services/sync/scheduler.py#L67-L78)).
- `schedule()` feeds the UI line "next check at ..." ([scheduler.py:32-36](../src/astra_rag/services/sync/scheduler.py#L32-L36)).

**Single active instance** ([instance.py](../src/astra_rag/services/sync/instance.py)). The lifespan takes an exclusive OS lock on
`<data dir>/astra.lock` (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere). A second instance on the same data
directory fails at startup with "Another Astra-RAG instance is already running ...", so it can never start a second
scheduler, sweep the first one's runs or race its recovery. The OS drops the lock when the process ends or crashes.
Order in the lifespan: lock → migrate + sweep → recovery → worker → scheduler
([`__init__.py:15-30`](../src/astra_rag/__init__.py#L15-L30)).

**Startup recovery** ([reconcile.py](../src/astra_rag/services/sync/reconcile.py)). The alias switch (Qdrant) and recording the run as `done`
(SQLite) can't share a transaction. If the process dies in between, the alias serves run N, the registry still names an
older build, and the restart sweep marks N `failed`. For each repo without an active run, `_repair`
([reconcile.py:34-56](../src/astra_rag/services/sync/reconcile.py#L34-L56)):

| Alias target | Action |
|---|---|
| version of run N, N newer than the indexed run, and run N has the matching collection and a commit | adopt it: [`runs.adopt_run`](../src/astra_rag/services/registry/runs.py#L98-L104) marks it `done` with "Recovered at startup: the index swap had completed." and records it as indexed. Safe because the alias is only switched after the count check passed. |
| a version the registry does not know, or older than the indexed run | keep it serving and ask for a forced rebuild ([`repos.request_rebuild`](../src/astra_rag/services/registry/repos.py#L42-L45)) |
| missing (or pointing at a deleted collection) while the registry says indexed | ask for a forced rebuild, unless a pre-P5 real collection still serves under the alias name |
| always | drop orphan versions through the guarded `delete_version` |

If Qdrant is unreachable, recovery is skipped with a log line and runs again before the next nightly pass
([reconcile.py:17-31](../src/astra_rag/services/sync/reconcile.py#L17-L31)). The forced rebuilds it asks for are started by the catch-up.

**Registry schema 2** ([db.py:58-64](../src/astra_rag/services/registry/db.py#L58-L64)): `repos.sync_pending`, `repos.sync_force`,
`repos.last_checked_at`, `repos.source_error` and `ingestion_runs.triggered_by` (`connect | manual | nightly |
settings | follow_up | catch_up`). Existing rows get the defaults; the upgrade is tested.

**Freshness** ([repos.py:92-129](../src/astra_rag/services/registry/repos.py#L92-L129)). The repo view adds `sync: {last_checked_at, pending,
source_error}` and a derived `sync_status`: `syncing` (run running), `queued`, `pending` (follow-up waiting),
`source_error`, `never_indexed`, `out_of_date` (`needs_rebuild`) or `up_to_date` (as of the last check).
`GET /api/repos` adds `schedule: {enabled, daily_at_utc, next_check_at}` ([routes.py:79](../src/astra_rag/routes.py#L79)).

**Connect, settings and routes.** `connections.connect` keeps its checks, then calls `register_and_queue` and
returns the run id (or `None` when folded into a follow-up) with the head it saw ([connections.py:39-48](../src/astra_rag/services/connections.py#L39-L48)).
`change_branch` starts a forced sync after a real change ([connections.py:64](../src/astra_rag/services/connections.py#L64)).
`validate_and_clone` hands a run to the worker and answers `queued` or `pending` ([routes.py:56-66](../src/astra_rag/routes.py#L56-L66));
`POST /api/repos/{slug}/sync` is one line over `request_sync` ([routes.py:87-89](../src/astra_rag/routes.py#L87-L89)).

**UI** ([app.js:9-101](../src/astra_rag/static/app.js#L9-L101), [index.html:30](../src/astra_rag/templates/index.html#L30), [index.html:39-42](../src/astra_rag/templates/index.html#L39-L42)).
The button reads **Check & sync**. Each repo row shows the indexed `branch @ sha` (full SHA on hover) and when it was
indexed, the sync status with "checked <time>", a red badge with the `source_error` message, and a **Sync now** button
(disabled while syncing or queued). Under the table: "Checked automatically every night at 02:00 UTC (next: ...).
Changes can take up to a day to appear; use Sync now to pick them up straight away."

**Logs and errors stay safe.** `source_error`, run errors and log lines hold only `AppError.message` (which adapters
build without the token or the host's reply) or an exception's type name. No tracebacks are logged by the sync code.

### Where

| What | File and lines |
|---|---|
| Sync service | [sync/service.py](../src/astra_rag/services/sync/service.py) |
| Worker | [sync/worker.py](../src/astra_rag/services/sync/worker.py) |
| Nightly scheduler and catch-up | [sync/scheduler.py](../src/astra_rag/services/sync/scheduler.py) |
| Startup recovery | [sync/reconcile.py](../src/astra_rag/services/sync/reconcile.py) |
| Single-instance lock | [sync/instance.py](../src/astra_rag/services/sync/instance.py) |
| Versions and alias | [store.py:21-37](../src/astra_rag/services/ingestion/store.py#L21-L37), [store.py:77-110](../src/astra_rag/services/ingestion/store.py#L77-L110) |
| Build, count check, swap, cleanup | [pipeline.py:34-102](../src/astra_rag/services/ingestion/pipeline.py#L34-L102) |
| Queueing, coalescing, follow-ups, adoption | [runs.py:15-70](../src/astra_rag/services/registry/runs.py#L15-L70), [runs.py:98-113](../src/astra_rag/services/registry/runs.py#L98-L113) |
| Check results, catch-up and recovery queries, `sync_status` | [repos.py:36-68](../src/astra_rag/services/registry/repos.py#L36-L68), [repos.py:92-129](../src/astra_rag/services/registry/repos.py#L92-L129) |
| Schema 2 | [db.py:58-64](../src/astra_rag/services/registry/db.py#L58-L64) |
| Lifespan order | [`__init__.py:15-30`](../src/astra_rag/__init__.py#L15-L30) |
| Config | [config.py:54-59](../src/astra_rag/config.py#L54-L59) |
| Routes | [routes.py:49-66](../src/astra_rag/routes.py#L49-L66), [routes.py:77-89](../src/astra_rag/routes.py#L77-L89) |
| Tests switch the scheduler off | [tests/\_\_init\_\_.py:8](../tests/__init__.py#L8) |

### Tests

| Test | What it proves |
|---|---|
| [test_sync.py:70](../tests/test_sync.py#L70) `test_unchanged_head_runs_nothing_and_records_the_check` | Same head → `up_to_date`, no run row, no clone, last check recorded. |
| [test_sync.py:81](../tests/test_sync.py#L81) `test_changed_head_builds_a_new_version_and_swaps_the_alias` | New head → new version, alias moved, old version gone, `source_url` carries the new SHA. |
| [test_sync.py:96](../tests/test_sync.py#L96) `test_a_branch_change_rebuilds_even_when_the_head_is_unchanged` | `needs_rebuild` forces a rebuild. |
| [test_sync.py:103](../tests/test_sync.py#L103) `test_config_version_is_stable_so_nightly_checks_stop_rebuilding` | After manual, nightly and forced syncs, `needs_rebuild` is false and the next nightly check runs nothing. |
| [test_sync.py:116](../tests/test_sync.py#L116) `test_triggers_during_a_run_coalesce_into_one_follow_up` | 6 concurrent Sync now requests during a run → all `pending`, exactly one follow-up run. |
| [test_sync.py:149](../tests/test_sync.py#L149) `test_a_failed_sync_keeps_the_old_index_serving` | Embedder crash → alias unchanged, half-built version deleted, search still answers. |
| [test_sync.py:160](../tests/test_sync.py#L160), [:172](../tests/test_sync.py#L172) | Revoked token / no saved token → `source_error`, old index serves; a good check clears it. |
| [test_sync.py:185](../tests/test_sync.py#L185) `test_errors_and_logs_never_contain_the_token` | Token and exception text absent from the repo view, run, `/api/repos` and captured logs. |
| [test_sync.py:202](../tests/test_sync.py#L202) `test_sync_now_route` | 404 / `up_to_date` / `queued` / `pending` through the API; `schedule` in `/api/repos`. |
| [test_sync.py:228](../tests/test_sync.py#L228) `test_a_completed_swap_is_adopted` | The crash between alias switch and `finish_run`, then recovery adopts the run. |
| [test_sync.py:237](../tests/test_sync.py#L237), [:248](../tests/test_sync.py#L248), [:260](../tests/test_sync.py#L260), [:266](../tests/test_sync.py#L266) | Unknown target → rebuild requested, alias untouched; orphans dropped but never the live version or an active run's; missing index → rebuild; Qdrant down → skipped. |
| [test_sync.py:277](../tests/test_sync.py#L277) `test_only_one_instance_per_data_directory` | A second lock fails with the clear message; free again after release. |
| [test_sync.py:292-317](../tests/test_sync.py#L292-L317) | `next_run_at` incl. midnight wrap, bad times rejected, one repo's failure doesn't stop a pass, thread starts with a catch-up and stops. |
| [test_ingestion.py:264](../tests/test_ingestion.py#L264), [:273](../tests/test_ingestion.py#L273) | Version names belong to one repo only; swap is one step; the live version is never deleted. |
| [test_ingestion.py:319](../tests/test_ingestion.py#L319), [:331](../tests/test_ingestion.py#L331), [:344](../tests/test_ingestion.py#L344), [:352](../tests/test_ingestion.py#L352) | Re-ingest swaps versions; **search is never empty during a rebuild**; a pre-P5 collection is replaced by the alias; a short count fails and keeps the old index. |
| [test_registry.py:61](../tests/test_registry.py#L61) `test_upgrading_from_schema_1_keeps_existing_rows` | Migration 1 → 2 keeps rows and applies defaults. |
| [test_registry.py:203](../tests/test_registry.py#L203), [:217](../tests/test_registry.py#L217), [:224](../tests/test_registry.py#L224), [:271](../tests/test_registry.py#L271) | Coalescing, a new run satisfies a waiting follow-up, unknown repo 404, 8 concurrent connects → 1 run + 1 follow-up. |
| [test_registry.py:229](../tests/test_registry.py#L229) `test_config_version_changes_only_with_the_tracked_branch` | Review point 1: only a branch change bumps it. |
| [test_registry.py:244](../tests/test_registry.py#L244), [:256](../tests/test_registry.py#L256) | `adopt_run` only adopts failed (swept) runs; check results and catch-up selection. |
| [test_routes.py:76](../tests/test_routes.py#L76), [:178](../tests/test_routes.py#L178), [:239](../tests/test_routes.py#L239) | Connect queues a background sync (no `path`); a second connect becomes a follow-up; a branch change starts a rebuild. |

### Plan vs delivered

| Plan item ([phases.md P5](../plan/phases.md)) | Status |
|---|---|
| Versioned collections behind an alias; build, check the count, swap, drop the old version | ✅ (names `astra_v<run>__<slug>`, see above) |
| `sync_repo`: check `head_sha`, skip if unchanged, otherwise clone and full ingest, then swap | ✅ as `request_sync` + `execute`; also skips only when the config is unchanged |
| Per-repo lock; a trigger during a sync is coalesced into one follow-up | ✅ the run row is the lock; `sync_pending`/`sync_force` |
| Nightly scheduler in the lifespan at `SYNC_DAILY_AT` | ✅ 02:00 UTC default, `ASTRA_SYNC_DAILY_AT`; plus a startup catch-up |
| `POST /api/repos/{slug}/sync` and a Sync now button; status shows last synced commit, time and state | ✅ plus last check, sync status and next check |
| Failure: old version keeps serving, error recorded, revoked token → `source_error` | ✅ |
| Tests: unchanged head, new version + swap, search during rebuild, coalescing, failed sync keeps old index | ✅ all five, plus recovery, lock, config stability, secrets |
| Out of scope: webhooks, hash-diff incremental ingest | ✅ respected |
| Added during plan review: config version stability, single instance enforced, crash recovery around the swap, credential and API-exposure notes, visible freshness | ✅ |
| Added: connect goes through the same background sync (agreed while planning) | ✅ API change: no `path`, no 409 |
| **Acceptance: push, Sync now, search shows the new text and the new SHA in `source_url`** | ⚠️ covered by tests with in-memory Qdrant; checked on a live server with a scratch database (startup with Qdrant down, Sync now errors, second instance refused). **Not yet run with a real repo, PAT and Qdrant.** |

---

## 9. Extra change shipped with P3: token saved as soon as the host accepts it

Not a plan item, but it is in commit `4607ba9` and listed separately in the CHANGELOG.

- **Before:** the PAT was saved to `.env` only after a successful clone.
- **After:** it is saved right after the root listing succeeds, before the structure check and clone. So a repo that
  fails validation (422) or whose clone fails still has its token saved, and a blank token field works next time. A
  token the host rejected is never saved, because the host call raises before the save line.
- **Since P4** this code is in `connections.connect` ([connections.py:40-42](../src/astra_rag/services/connections.py#L40-L42)),
  the listing is of the tracked branch, and the URL saved with the token is the cleaned `web_url`. Because
  `default_branch()` and `head_sha()` now run before the listing, a valid token typed together with a branch that does
  not exist is not saved (the listing never ran).
- The 422 body includes `token_saved` ([routes.py:51-55](../src/astra_rag/routes.py#L51-L55)), and the UI clears the
  token field and says "(token saved for this repository)" ([app.js:161-163](../src/astra_rag/static/app.js#L161-L163)).
- `CLAUDE.md`'s security rule was updated to describe this.
- Tests: [test_routes.py:140](../tests/test_routes.py#L140) (saved even if clone fails),
  [:162](../tests/test_routes.py#L162) (rejected token not saved),
  [:169](../tests/test_routes.py#L169) (missing structure saves token, nothing queued).

---

## 10. Work done before the phases (W0, W1) that P0-P5 build on

These were done before `plan/phases.md` existed. They are summarised so you can trace the full flow.

### W0: connector (2026-10-26)
URL parse, root listing, structure validation, clone. Now spread across `connections`, the adapter registry, adapters,
`validator` and `cloner`.

### W1: RAG ingestion pipeline (2026-10-27)

| Step | What | Where |
|---|---|---|
| Load | Walk `project-data/`; load `.md/.markdown/.txt/.csv/.docx`; skip hidden, unsupported, empty, >25 MB, unreadable; docx → markdown via `markitdown`; sha256 per file. | [loader.py](../src/astra_rag/services/ingestion/loader.py), types in [config.py:49-51](../src/astra_rag/config.py#L49-L51) |
| Chunk markdown | Split by heading with a breadcrumb path; code fences and tables kept whole if they fit; oversize tables repeat header rows; very long lines cut into overlapping word windows; headings never end a chunk; tiny last chunk folded back. Line ranges tracked. | [md_chunker.py](../src/astra_rag/services/ingestion/md_chunker.py) |
| Chunk CSV | Auto-detect delimiter; one summary chunk (columns, row count, first 3 rows) + row-group chunks with the column header repeated; row ranges tracked; capped at 100k rows with a warning. | [csv_chunker.py](../src/astra_rag/services/ingestion/csv_chunker.py) |
| Token budget | Cheap, slightly pessimistic token estimate; target 380, cap 480 (below bge's 512). | [tokens.py](../src/astra_rag/services/ingestion/tokens.py), [config.py:42-47](../src/astra_rag/config.py#L42-L47) |
| Metadata | Every chunk payload: repo, repo_slug, host, owner, branch, commit_sha, path, filename, folder_parts, folder_top, file_type, file_hash, title, chunk_id, chunk_index, chunk_kind, heading_path, line or row range, `source_url` (from adapter), text. `chunk_id = sha1(path, index, sha1(text))`. | [chunker.py:14-58](../src/astra_rag/services/ingestion/chunker.py#L14-L58) |
| Embed | Local `fastembed`: dense `BAAI/bge-base-en-v1.5` (768-d) + sparse `Qdrant/bm25`, batches of 32. Text embedded = breadcrumb + chunk text. | [embedder.py](../src/astra_rag/services/ingestion/embedder.py), [chunker.py:56-58](../src/astra_rag/services/ingestion/chunker.py#L56-L58) |
| Store | Qdrant collection `astra__<slug>`, dropped and recreated each ingest (**since P5** a new version collection per build behind the alias `astra__<slug>`, see §8); named vectors `dense` (cosine) + `sparse` (IDF); keyword indexes on path, folder_top, file_type, file_hash, commit_sha; point id = UUIDv5(chunk_id). | [store.py:17-61](../src/astra_rag/services/ingestion/store.py#L17-L61) |
| Search | Hybrid: dense + sparse prefetch (3× limit, min 20), fused with RRF; optional `folder_top` / `file_type` filters. Missing collection → 404. Since P5 it reads through the alias. | [store.py:112-141](../src/astra_rag/services/ingestion/store.py#L112-L141) |
| Status | Was in memory per slug in W1. **Since P4** it is the run row in SQLite: queued/running/done/failed, counts, skipped files, warnings, error, timestamps. `run_ingestion` never raises; errors are recorded on the run. | [pipeline.py:20-56](../src/astra_rag/services/ingestion/pipeline.py#L20-L56), [registry/runs.py](../src/astra_rag/services/registry/runs.py) |

---

## 11. Security controls: where each one is enforced

| Rule (from `CLAUDE.md`) | How it is enforced | Where | Test |
|---|---|---|---|
| PAT stored only in git-ignored `.env` | `token_store` writes `.env`; `.env` and `.env.*` are in `.gitignore` | [token_store.py:95-103](../src/astra_rag/services/token_store.py#L95-L103), [.gitignore](../.gitignore) | [test_token_store.py](../tests/test_token_store.py) |
| PAT saved only after the host accepted it | save is after the root listing of the tracked branch succeeds | [connections.py:40-42](../src/astra_rag/services/connections.py#L40-L42) | [test_routes.py:162](../tests/test_routes.py#L162) |
| `.env` never half-written | write to temp file, then `os.replace`; `chmod 600` where supported | [token_store.py:77-92](../src/astra_rag/services/token_store.py#L77-L92) | n/a |
| PAT never in the registry database | `repos.credential_ref` holds only the `.env` key name | [token_store.py:106-108](../src/astra_rag/services/token_store.py#L106-L108), [db.py:14-30](../src/astra_rag/services/registry/db.py#L14-L30) | [test_registry.py:87](../tests/test_registry.py#L87) |
| PAT never returned by any API | responses carry only `token_saved` / `token_reused`; the repo view omits `credential_ref` | [routes.py:56-66](../src/astra_rag/routes.py#L56-L66), [repos.py:92-114](../src/astra_rag/services/registry/repos.py#L92-L114) | [test_routes.py:128](../tests/test_routes.py#L128), [:232](../tests/test_routes.py#L232) |
| PAT never in repr/str/logs | `PatCredential` redacted, `__slots__` | [credentials.py:9-23](../src/astra_rag/services/sources/credentials.py#L9-L23) | [test_credentials.py](../tests/sources/test_credentials.py) |
| PAT never in URL, `.git/config` or process args | header passed via `GIT_CONFIG_*` env vars | [git.py:12-24](../src/astra_rag/services/sources/git.py#L12-L24) | [test_git.py:25](../tests/sources/test_git.py#L25), [contract.py:116](../tests/sources/contract.py#L116) |
| Typed URL credentials never stored or echoed | stored URL is rebuilt from the `RepoRef` (`web_url`); URL errors are fixed messages | [connections.py:42](../src/astra_rag/services/connections.py#L42), [:47](../src/astra_rag/services/connections.py#L47), [base.py:42-45](../src/astra_rag/services/sources/base.py#L42-L45) | [test_routes.py:194](../tests/test_routes.py#L194), [:205](../tests/test_routes.py#L205) |
| Branch names cannot become git options | strict pattern checked before any host or git call; git gets it as a separate argument after `--branch` | [rules.py:8-13](../src/astra_rag/services/registry/rules.py#L8-L13), [config.py:25](../src/astra_rag/config.py#L25) | [test_routes.py:121](../tests/test_routes.py#L121), [test_registry.py:298](../tests/test_registry.py#L298) |
| No SQL injection in the registry | bound parameters everywhere; UPDATE column names only from a fixed allow-list | [runs.py:116-122](../src/astra_rag/services/registry/runs.py#L116-L122) | [test_registry.py:289](../tests/test_registry.py#L289) |
| PAT cleared from the page | UI blanks the field after success or a 422 with `token_saved` | [app.js:156](../src/astra_rag/static/app.js#L156), [app.js:162](../src/astra_rag/static/app.js#L162) | n/a (manual) |
| Error messages safe to show | `AppError` only; host body never included; unexpected errors are a generic 500 | [sources/errors.py](../src/astra_rag/services/sources/errors.py), [`__init__.py:38-40`](../src/astra_rag/__init__.py#L38-L40) | [contract.py:84](../tests/sources/contract.py#L84), [test_routes.py:150](../tests/test_routes.py#L150) |
| Repo cannot pull outside files into the index | loader link checks + `core.symlinks=false` | [loader.py:37-42](../src/astra_rag/services/ingestion/loader.py#L37-L42), [git.py:23](../src/astra_rag/services/sources/git.py#L23) | [test_ingestion.py:119-152](../tests/test_ingestion.py#L119-L152) |
| Hosts' tokens kept apart | host-aware slug keys | [repo_ref.py:20-23](../src/astra_rag/services/repo_ref.py#L20-L23) | [test_token_store.py:44](../tests/test_token_store.py#L44) |
| Clones, vector data and the registry not committed | `temp_storage/*`, `.cache/`, `data/` git-ignored; Qdrant data in a Docker volume | [.gitignore](../.gitignore), [docker-compose.yml](../docker-compose.yml) | tests never create `data/` ([tests/\_\_init\_\_.py](../tests/__init__.py)) |
| Blocking I/O off the event loop | routes are plain `def` (FastAPI runs them in a worker thread); since P5 clone and ingest run on the sync worker thread, the nightly check on its own daemon thread | [routes.py:48-50](../src/astra_rag/routes.py#L48-L50), [worker.py:13-17](../src/astra_rag/services/sync/worker.py#L13-L17) | n/a |
| Sync errors and logs carry no secrets (P5) | `source_error`, run errors and sync log lines hold only `AppError.message` or an exception's type name; no tracebacks | [service.py:55-104](../src/astra_rag/services/sync/service.py#L55-L104), [scheduler.py:67-78](../src/astra_rag/services/sync/scheduler.py#L67-L78), [worker.py:37-41](../src/astra_rag/services/sync/worker.py#L37-L41) | [test_sync.py:185](../tests/test_sync.py#L185) |
| One instance owns the runs (P5) | exclusive OS lock on `data/astra.lock` before the sweep, recovery, worker and scheduler start | [instance.py](../src/astra_rag/services/sync/instance.py), [`__init__.py:17-18`](../src/astra_rag/__init__.py#L17-L18) | [test_sync.py:277](../tests/test_sync.py#L277) |
| The live index is never deleted (P5) | every version delete re-reads the alias target first | [store.py:99-106](../src/astra_rag/services/ingestion/store.py#L99-L106) | [test_ingestion.py:273](../tests/test_ingestion.py#L273), [test_sync.py:248](../tests/test_sync.py#L248) |
| **API access control** | **none yet.** Every endpoint, including repo and project management and Sync now (which triggers host calls and CPU-heavy embedding), is open to anyone who can reach the server. Keep it on `127.0.0.1` (the default in `main()`) or behind an authenticating reverse proxy; never expose it directly to the internet. | [`__init__.py:45-53`](../src/astra_rag/__init__.py#L45-L53) | n/a |

---

## 12. Reference: endpoints, config, stored data, dependencies

### Endpoints

| Method + path | Body / params | Returns | Code |
|---|---|---|---|
| `GET /` | none | the HTML page | [routes.py:40-45](../src/astra_rag/routes.py#L40-L45) |
| `POST /api/validate-and-clone` | `{url, token, branch?}` (blank token = use saved; blank branch = saved tracked branch, else host default) | 200 `{ok, message, branch, commit_sha (head at connect), token_saved, token_reused, ingestion:{slug, run_id, state: queued \| pending}}` (P5: no `path`, no 409; `run_id` is null when `pending`); 404 branch not found; 422 `{ok:false, missing[], token_saved, error}`; other errors `{ok:false, error}` | [routes.py:49-66](../src/astra_rag/routes.py#L49-L66) |
| `GET /api/ingestion-status/{slug}` | slug | latest run: `{ok, run_id, state, branch, commit_sha, collection, files_loaded, files_skipped[], chunks_total, chunks_stored, warnings[], error, queued_at, started_at, finished_at, triggered_by}`; 404 if never started | [routes.py:69-74](../src/astra_rag/routes.py#L69-L74) |
| `GET /api/repos` | none | `{ok, repos:[{slug, url, host_kind, host, tracked_branch, index_state, needs_rebuild, sync_status, sync:{last_checked_at, pending, source_error}, indexed:{run_id, branch, commit_sha, collection, at} or null, last_run, projects[], created_at, updated_at}], schedule:{enabled, daily_at_utc, next_check_at}}` | [routes.py:77-79](../src/astra_rag/routes.py#L77-L79) |
| `PUT /api/repos/{slug}/settings` | `{tracked_branch}` | `{ok, repo}`; a real change starts a rebuild (P5); 400 bad name or no saved token; 404 repo not registered or branch not found | [routes.py:82-84](../src/astra_rag/routes.py#L82-L84) |
| `POST /api/repos/{slug}/sync` (P5) | none | `{ok, slug, state: up_to_date, commit_sha}` / `{..., state: queued, run_id}` / `{..., state: pending}`; 404 not registered; 400 no saved token; host errors (e.g. 401) with a safe message | [routes.py:87-89](../src/astra_rag/routes.py#L87-L89) |
| `PUT /api/projects/{project_id}/binding` | `{repo_slug}` | `{ok, project:{project_id, bound_at, repo}}`; 404 repo not registered; 422 bad project id | [routes.py:92-94](../src/astra_rag/routes.py#L92-L94) |
| `GET /api/projects/{project_id}` | project id | `{ok, project}`; 404 not bound; 422 bad id | [routes.py:97-102](../src/astra_rag/routes.py#L97-L102) |
| `POST /api/search` | `{slug, query, limit=8 (1-50), folder?, file_type?}` | `{ok, results:[payload + score]}` | [routes.py:105-109](../src/astra_rag/routes.py#L105-L109) |
| `GET /docs` | none | FastAPI OpenAPI UI | built in |

### Config ([config.py](../src/astra_rag/config.py))

| Setting | Value | Line |
|---|---|---|
| `REQUIRED_FILES` / `REQUIRED_FOLDERS` | `policies.md`, `nomenclature.md` / `project-data`, `templates` | [12-13](../src/astra_rag/config.py#L12-L13) |
| `SUPPORTED_HOST_KINDS` | `github`, `ghe`, `azure_devops` | [16](../src/astra_rag/config.py#L16) |
| `GIT_TIMEOUT_SECONDS` / `HTTP_TIMEOUT_SECONDS` | 300 / 20 | [18-19](../src/astra_rag/config.py#L18-L19) |
| `DB_PATH` / `DB_BUSY_TIMEOUT_SECONDS` | env `ASTRA_DB_PATH`, default `data/astra.db` / 5 | [22-23](../src/astra_rag/config.py#L22-L23) |
| `BRANCH_NAME_PATTERN` / `PROJECT_ID_PATTERN` | strict ref-name subset / `[A-Za-z0-9._-]{1,64}` | [25-26](../src/astra_rag/config.py#L25-L26) |
| `QDRANT_URL` / `QDRANT_API_KEY` | env, default `http://localhost:6333` | [33-34](../src/astra_rag/config.py#L33-L34) |
| Models | `BAAI/bge-base-en-v1.5` (768), `Qdrant/bm25` | [37-39](../src/astra_rag/config.py#L37-L39) |
| Chunk sizes | target 380, max 480, min 100, overlap 50 | [43-46](../src/astra_rag/config.py#L43-L46) |
| File limits | 25 MB, 100k CSV rows | [50-51](../src/astra_rag/config.py#L50-L51) |
| `ENV_FILE` | `<repo root>/.env` | [52](../src/astra_rag/config.py#L52) |
| `SYNC_DAILY_AT` (P5) | env `ASTRA_SYNC_DAILY_AT`, `HH:MM` in UTC, default `02:00` | [55](../src/astra_rag/config.py#L55) |
| `SYNC_SCHEDULER_ENABLED` (P5) | env `ASTRA_SYNC_SCHEDULER`, default on; `0` turns off the nightly check, catch-up and startup recovery (tests set it) | [57](../src/astra_rag/config.py#L57) |
| `SYNC_WORKERS` / `SYNC_CATCHUP_HOURS` (P5) | 1 / 24 | [58-59](../src/astra_rag/config.py#L58-L59) |

The schema version is not a config value: it is the number of entries in `registry/db.MIGRATIONS` (2 since P5).

### What is stored where

| Data | Location | Survives restart? | Keyed by |
|---|---|---|---|
| Repo URL (cleaned) + PAT | `.env` at repo root (git-ignored) | yes | `ASTRA_REPO_<SLUG>_URL/_TOKEN` |
| Repos, tracked branch, last good build, project bindings | SQLite `data/astra.db` (git-ignored) | yes | slug / project id |
| Ingestion runs (status history) | SQLite `data/astra.db`, table `ingestion_runs` | yes (active runs are marked failed at startup) | run id, slug |
| Sync state per repo (P5): follow-up waiting, last check, source error | SQLite `data/astra.db`, table `repos` | yes | slug |
| Single-instance lock (P5) | `data/astra.lock` (git-ignored; the OS lock is released when the process ends) | the file stays, the lock does not | data directory |
| Cloned repo | `temp_storage/<slug>/` (git-ignored) | yes, replaced on every sync | slug |
| Chunks + vectors | Qdrant collection `astra_v<run>__<slug>` behind the alias `astra__<slug>` (P5; before P5 a real collection `astra__<slug>`), in Docker volume `qdrant_storage` | yes | slug, run id |
| Embedding models | `.cache/fastembed` (git-ignored) | yes | model name |

### Dependencies ([pyproject.toml](../pyproject.toml))
`fastapi`, `uvicorn[standard]`, `jinja2`, `qdrant-client`, `fastembed`, `markitdown[docx]`; dev: `httpx` (for
FastAPI's `TestClient`). P0-P5 added **no new dependencies**: host REST calls use the standard library `urllib`,
the registry uses the standard library `sqlite3`, and the sync worker, scheduler and instance lock use `threading`,
`concurrent.futures`, `msvcrt` / `fcntl`.

---

## 13. Test inventory

Run: `uv run python -m unittest discover -s tests -t .` → **177 tests, OK, 1 skipped** (2026-10-28, working tree with P5).
The skipped test is `test_file_link_is_skipped_and_reported`: this Windows machine cannot create symlinks.

| File | Covers | Phase(s) |
|---|---|---|
| [tests/test_ingestion.py](../tests/test_ingestion.py) | loader (incl. symlinks), md and CSV chunkers, metadata, pipeline end to end on in-memory Qdrant with a fake embedder, run outcomes in the registry, version collections and alias swap, search during a rebuild | W1, P0, P1, P4, P5 |
| [tests/test_routes.py](../tests/test_routes.py) | all API routes with a fake host (adapter, token store, clone, ingestion) on a temporary database: connect through the background sync, branch handling, follow-ups, failures, URL cleaning, repos, settings, bindings, restart | P1-P5 |
| [tests/test_registry.py](../tests/test_registry.py) | migrations (incl. 1 → 2), foreign keys, repos and bindings, run lifecycle, coalescing, `config_version` stability, adoption, check results, concurrency, input rules | P4, P5 |
| [tests/test_sync.py](../tests/test_sync.py) | sync service on in-memory Qdrant (head check, swap, coalescing, failures, source errors, secrets), Sync now route, startup recovery, instance lock, scheduler | P5 |
| [tests/test_token_store.py](../tests/test_token_store.py) | save/get/forget, host separation, legacy migration | P1 |
| [tests/test_validator_and_url.py](../tests/test_validator_and_url.py) | structure check, URL parsing, host-aware slugs | W0, P1 |
| [tests/test_cloner.py](../tests/test_cloner.py) | clone folder naming, replacement, branch pass-through | P1, P2 |
| [tests/helpers.py](../tests/helpers.py), [tests/\_\_init\_\_.py](../tests/__init__.py) | temporary registry per test; `ASTRA_DB_PATH` safety net; `ASTRA_SYNC_SCHEDULER=0` | P4, P5 |
| [tests/sources/contract.py](../tests/sources/contract.py) | shared adapter contract (11 tests per adapter, incl. `web_url` and single-branch clone) | P2, P4 |
| [tests/sources/fake_http.py](../tests/sources/fake_http.py) | fake `urlopen` used by contract tests | P2 |
| [tests/sources/test_github.py](../tests/sources/test_github.py) | GitHub contract + specifics (incl. URL cleaning) | P2, P4 |
| [tests/sources/test_azure_devops.py](../tests/sources/test_azure_devops.py) | ADO contract + URL parsing + specifics (incl. URL cleaning) | P3, P4 |
| [tests/sources/test_git.py](../tests/sources/test_git.py) | shared clone helper | P0, P2 |
| [tests/sources/test_credentials.py](../tests/sources/test_credentials.py) | `PatCredential` redaction | P2 |
| [tests/sources/test_registry.py](../tests/sources/test_registry.py) | adapter dispatch, config/registry agreement | P2, P3 |
| [tests/fixtures/repo/project-data/](../tests/fixtures/repo/project-data/) | sample md, txt, csv, empty csv, png | W1 |

No test uses the network or a real token. Qdrant tests use `QdrantClient(":memory:")`; embeddings use a fake embedder;
the registry uses a fresh temporary SQLite file per test. The registry and route suites were run 5 more times in a
row to check the concurrency test is not flaky; all passed. The sync tests patch only the host, the `.env` store and git;
the sync service, pipeline and Qdrant code are the real ones.

---

## 14. Open items, gaps and limitations

### Manual checks still to run
1. **P3 acceptance:** no real Azure DevOps repo has been connected yet. Three things to check when it is:
   - the citation link's line highlighting (`lineEnd = end + 1` with column 1) lands on the right lines;
   - whether ADO lists root names in their real case (our validator enforces exact case either way);
   - `is_ancestor` via `diffs/commits` `behindCount` gives the expected answer (not used by any route yet).
2. **P4 acceptance with a real repo:** connect, restart the app, confirm the repo list and last status are still there;
   `PUT` a new branch, reconnect, and confirm the clone and the chunks' `commit_sha` / `source_url` are from that branch.
3. **P0 acceptance on Windows:** the symlink test is skipped on this machine. The CHANGELOG says it was verified on
   Linux in Docker.
4. **P5 acceptance with a real repo and Qdrant** (see [§15](#15-how-to-verify-this-yourself)): push, Sync now, new text
   and new SHA in search; search never empty during the rebuild; a double click gives `pending` and one follow-up; the
   nightly check with `ASTRA_SYNC_DAILY_AT` set a few minutes ahead; a revoked PAT shows `source_error`; one `astra_v*`
   collection per repo in the Qdrant dashboard; the crash drill (kill the process right after the alias switch, restart,
   the run is recovered). Already done: startup with Qdrant down, Sync now errors and the second-instance refusal, on a
   scratch database.

### Known limitations (by design for now)
1. **No API authentication.** All endpoints, including repo and project management and Sync now, are unauthenticated.
   Keep the server on `127.0.0.1` or behind an authenticating reverse proxy; never expose it directly to the internet.
2. ~~No atomic Qdrant index replacement~~: fixed in P5 (versioned collections behind an alias).
3. ~~Rebuilds are manual~~: fixed in P5 (nightly check, Sync now, a branch change rebuilds at once, follow-ups instead
   of 409).
4. **One app instance on SQLite.** The design assumes a single process, and since P5 this is enforced by the lock on
   `data/astra.lock`. Several replicas (or Postgres) would need shared scheduling, distributed run ownership and a
   different recovery story, not only a connection string.
5. **Token not saved when the branch is wrong.** A valid PAT typed together with a branch that does not exist is not
   saved, because the root listing never ran (this follows the "save after the root listing" rule).
6. **Existing repos appear on their next connect.** Repos connected before P4 are not imported from `.env` into the
   registry; they show up the next time they are connected.
7. **No delete:** repos and project bindings cannot be removed through the API yet.
8. **Adapter methods not wired in yet:** `read_file` and `is_ancestor` are implemented and tested, but no route calls
   them. P7 and P9 will use `read_file`; P5 did not need `is_ancestor`. (`head_sha` and `default_branch` are used since
   P4, and `head_sha` is also the P5 sync check.)
9. **Freshness is daily unless someone clicks Sync now** (P5, by design: no customer-side setup). A push can take up
    to about 24 hours to reach search. Webhooks would make it instant but need a public URL and per-repo setup by the
    customer; the `verify_webhook` slot is reserved and `request_sync(slug, "webhook")` is the call it would make.
10. **Every sync is a full rebuild** (fine for repos under ~100 files); hash-diff incremental ingest is a later item.
11. **`ASTRA_SYNC_SCHEDULER=0` also turns off startup recovery.** It is meant for tests and maintenance only.

### Doc drift found in the P0-P3 review: fixed in P4
1. Branch name in [CURRENT_STATE.md](CURRENT_STATE.md) and [CLAUDE.md](../CLAUDE.md): now `goldan-repo-re-guru`. ✅
2. README security note (token key and when it is saved): rewritten. ✅
3. `pyproject.toml` description: now mentions Azure DevOps. ✅
4. README structure block: `routes.py`, `connections.py`, `registry/` and `data/` described. ✅

### Small code observations
1. **Any unknown host is treated as GitHub Enterprise** ([repo_ref.py:35](../src/astra_rag/services/repo_ref.py#L35)).
   A self-hosted GitLab on a name not starting with `gitlab.` would be sent to the GitHub adapter and fail with a
   GitHub-flavoured error. Acceptable now; worth revisiting in P10.
2. **`_field` is duplicated** in [github.py:91-97](../src/astra_rag/services/sources/github.py#L91-L97) and
   [azure_devops.py:141-147](../src/astra_rag/services/sources/azure_devops.py#L141-L147) with only the label
   different. It could move to a shared helper.
3. **Two things called "registry":** `services/sources/registry.py` (host → adapter) and `services/registry/` (the
   database). The paths keep them apart, but a rename of one of them would help readers.
4. ~~Ingestion status is in memory~~: fixed in P4.
5. ~~Re-ingest drops the live collection first~~: fixed in P5 ([store.py:84-94](../src/astra_rag/services/ingestion/store.py#L84-L94)).
6. **`index_replaced` and `incomplete` are now legacy** (P5): kept so runs from before P5 still report honestly; no new
   run sets them.

---

## 15. How to verify this yourself

```powershell
# 1. See exactly what each phase changed
git show --stat f7ed92a   # P0
git show --stat 764eb13   # P1
git show --stat e994236   # P2
git show --stat 4607ba9   # P3
git show --stat 36cd57c   # P4
git status; git diff --stat   # P5 (not committed yet; services/sync/ and tests/test_sync.py show as untracked)
git show 4607ba9 -- src/astra_rag/services/sources/azure_devops.py

# 2. Run all tests (no network or tokens needed)
uv run python -m unittest discover -s tests -t .

# 3. Run one phase's tests
uv run python -m unittest tests.test_sync -v                             # P5
uv run python -m unittest tests.test_registry tests.test_routes -v       # P4 (and the P5 changes to them)
uv run python -m unittest tests.sources.test_azure_devops -v       # P3
uv run python -m unittest tests.sources.test_github tests.sources.test_git tests.sources.test_credentials -v   # P2
uv run python -m unittest tests.test_token_store tests.test_validator_and_url -v   # P1
uv run python -m unittest tests.test_ingestion.LoaderSymlinkTests -v   # P0

# 4. Run the app end to end
docker compose up -d qdrant
uv run python -m astra_rag      # http://127.0.0.1:5000, API docs at /docs
```

**Manual check for P3 acceptance (still to do):** connect a real ADO golden repo in the UI, wait for "Ingestion done",
then `POST /api/search` with that repo's `slug` and open a result's `source_url` in the browser. It should open the file
in ADO at commit `GC<sha>` with the right lines highlighted.

**Manual check for P4 acceptance (still to do):**
1. Connect a real repo (blank branch). The repos table shows its default branch and, when done, `ready`.
2. Stop and restart the app. The table and `GET /api/ingestion-status/{slug}` still show the repo and its last run.
3. `PUT /api/repos/{slug}/settings` with `{"tracked_branch": "<another branch>"}`. The table shows "rebuild pending".
4. Connect again with a blank token and branch. When done, `GET /api/repos` shows `indexed.branch` = the new branch,
   `needs_rebuild: false`, and search results carry that branch's commit in `source_url`.
5. Optional: `PUT /api/projects/demo/binding` with `{"repo_slug": "<slug>"}`, then `GET /api/projects/demo`.

**Manual check for P5 acceptance (still to do):**
1. With Qdrant running, connect a real repo and wait for `up to date` in the repos table.
2. Push an edit to the tracked branch, click **Sync now**, wait for the run to finish, then `POST /api/search`: the new
   text is found and `source_url` carries the new commit SHA.
3. While that sync runs, search in a loop: it never returns empty.
4. Click Sync now twice quickly: the second says another sync will follow, and exactly one follow-up run happens.
5. Set `ASTRA_SYNC_DAILY_AT` to two minutes from now (UTC) and restart: the nightly check runs; with no new commit the
   repo stays `up to date` and no run is added.
6. Revoke the PAT and click Sync now: the row shows "cannot reach the repository" with the reason, and search still works.
   Reconnect with a new PAT (branch blank): the error clears.
7. Qdrant dashboard: one `astra_v<run>__<slug>` collection per repo, with the alias `astra__<slug>` pointing at it.
8. Start a second `uv run python -m astra_rag` on the same data directory: it refuses to start.
9. Crash drill: stop the process right after the alias switch (for example a breakpoint after `swap_alias` in
   `pipeline._ingest`), restart: the repo is indexed at the new commit and the run says "Recovered at startup".
