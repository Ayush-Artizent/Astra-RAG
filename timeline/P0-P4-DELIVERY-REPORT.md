# Delivery report: phases P0 to P4

_Written 2026-10-28 against branch `goldan-repo-re-guru`. P0-P3 are commits `f7ed92a` to `4607ba9`; **P4 is in the working tree and not committed yet**._
_Plan being checked: [plan/phases.md](../plan/phases.md). Test run on the working tree: **145 tests, all pass, 1 skipped** (a symlink test that cannot run on Windows). At `4607ba9` (end of P3) it was 105._

This report explains, in plain English, what has been built in phases P0 to P4, how each part works, and
exactly where the code and tests are. Every claim links to a file and line, so you can open it and check it yourself.
Links are relative to this file and open in VS Code or on GitHub.

**All line links point at the current working tree (P4 included).** Where P4 replaced code that an earlier phase
delivered (mainly `routes.py` and the in-memory ingestion status), the earlier section says so; `git show <commit>`
shows the original.

---

## Contents
1. [How to use this report](#1-how-to-use-this-report)
2. [The app in one page (end-to-end flow today)](#2-the-app-in-one-page-end-to-end-flow-today)
3. [Phase P0: Safety fixes and doc cleanup](#3-phase-p0-safety-fixes-and-doc-cleanup)
4. [Phase P1: Host-aware repo identity](#4-phase-p1-host-aware-repo-identity)
5. [Phase P2: Source adapter port + GitHub adapter](#5-phase-p2-source-adapter-port--github-adapter)
6. [Phase P3: Azure DevOps adapter](#6-phase-p3-azure-devops-adapter)
7. [Phase P4: Repo registry, project bindings and tracked branch](#7-phase-p4-repo-registry-project-bindings-and-tracked-branch)
8. [Extra change shipped with P3: token saved as soon as the host accepts it](#8-extra-change-shipped-with-p3-token-saved-as-soon-as-the-host-accepts-it)
9. [Work done before the phases (W0, W1) that P0-P4 build on](#9-work-done-before-the-phases-w0-w1-that-p0-p4-build-on)
10. [Security controls: where each one is enforced](#10-security-controls-where-each-one-is-enforced)
11. [Reference: endpoints, config, stored data, dependencies](#11-reference-endpoints-config-stored-data-dependencies)
12. [Test inventory](#12-test-inventory)
13. [Open items, gaps and limitations](#13-open-items-gaps-and-limitations)
14. [How to verify this yourself](#14-how-to-verify-this-yourself)

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
| P4 | not committed yet | 33 (8 new) | +1235 / -177 (code, tests and docs, from `git diff --stat` including the new files) |

- **Status words used below:** ✅ done and tested · ⚠️ done in code but not verified against a real host · ❌ not done.

---

## 2. The app in one page (end-to-end flow today)

The user opens the page, enters a repo URL (GitHub, GitHub Enterprise or Azure DevOps), a personal access token (PAT)
and optionally a branch to track, and clicks **Check & clone**. The route
[`validate_and_clone`](../src/astra_rag/routes.py#L48-L62) is thin: it calls
[`connections.connect`](../src/astra_rag/services/connections.py#L28-L61) and then starts the ingestion in the background.

| Step | What happens | Where |
|---|---|---|
| 1 | The browser posts `{url, token, branch}` to `POST /api/validate-and-clone`. | [app.js:88-118](../src/astra_rag/static/app.js#L88-L118) |
| 2 | The URL is parsed into a `RepoRef` (host kind, host, path parts, name). The adapter registry checks scheme and host, then hands the rest of the URL to that host's adapter. | [connections.py:33](../src/astra_rag/services/connections.py#L33) → [registry.py:19-27](../src/astra_rag/services/sources/registry.py#L19-L27) |
| 3 | The token is the one typed in, or, if the field is blank, the one saved in `.env` for this repo. No token at all gives a 400. | [connections.py:34-37](../src/astra_rag/services/connections.py#L34-L37) → [token_store.get_token](../src/astra_rag/services/token_store.py#L111-L115) |
| 4 | A typed branch name is checked against a strict pattern **before any host call** (no leading `-`, no `..`, ...). | [connections.py:38](../src/astra_rag/services/connections.py#L38) → [rules.check_branch_name](../src/astra_rag/services/registry/rules.py#L8-L13) |
| 5 | The host's adapter is picked, with the token wrapped in a `PatCredential`. The branch is the typed one, else the repo's saved tracked branch, else the host's default branch. | [connections.py:40-41](../src/astra_rag/services/connections.py#L40-L41) → [repos.tracked_branch](../src/astra_rag/services/registry/repos.py#L9-L12) |
| 6 | `head_sha(branch)` confirms the branch exists (404 "Branch not found" otherwise). | [connections.py:42](../src/astra_rag/services/connections.py#L42) |
| 7 | The root **of that branch** is listed. That worked, so the host accepted the token: a typed token is saved to `.env` with the cleaned URL (`adapter.web_url`). | [connections.py:43-45](../src/astra_rag/services/connections.py#L43-L45) → [token_store.save](../src/astra_rag/services/token_store.py#L95-L103) |
| 8 | The listing is checked for `policies.md`, `nomenclature.md`, `project-data/` and `templates/` (exact case). Anything missing → HTTP 422 listing the missing items. Nothing is registered. | [connections.py:46-48](../src/astra_rag/services/connections.py#L46-L48) → [validator.find_missing](../src/astra_rag/services/validator.py#L5-L11) |
| 9 | **One SQLite transaction:** if the repo already has a queued or running run → 409; otherwise the repo row is inserted or updated and a `queued` run is created. | [connections.py:50-51](../src/astra_rag/services/connections.py#L50-L51) → [runs.queue_run](../src/astra_rag/services/registry/runs.py#L14-L35) |
| 10 | The tracked branch is shallow-cloned (`--branch <b> --single-branch`) into `temp_storage/<slug>/`, replacing any older clone. A clone failure finishes the run as `failed`. | [connections.py:52-59](../src/astra_rag/services/connections.py#L52-L59) → [cloner.clone_repo](../src/astra_rag/services/cloner.py#L12-L18) → [git.git_clone](../src/astra_rag/services/sources/git.py#L11-L34) |
| 11 | The commit SHA goes on the run; the route starts the ingestion as a background task and returns `slug`, `branch` and `run_id` straight away. | [connections.py:60-61](../src/astra_rag/services/connections.py#L60-L61), [routes.py:56-62](../src/astra_rag/routes.py#L56-L62) |
| 12 | Background: load `project-data/` → chunk → embed → store in Qdrant, writing progress to the run row. A `done` run becomes the repo's indexed build. | [pipeline.run_ingestion](../src/astra_rag/services/ingestion/pipeline.py#L30-L46), [_ingest](../src/astra_rag/services/ingestion/pipeline.py#L49-L84), [runs.finish_run](../src/astra_rag/services/registry/runs.py#L48-L65) |
| 13 | The browser polls `GET /api/ingestion-status/{slug}` every 1.5 s (read from SQLite) until done or failed, then refreshes the repos table. | [app.js:72-86](../src/astra_rag/static/app.js#L72-L86) → [routes.py:65-70](../src/astra_rag/routes.py#L65-L70) → [runs.latest_run](../src/astra_rag/services/registry/runs.py#L77-L81) |
| 14 | The repos table (`GET /api/repos`) shows each repo's tracked branch, indexed branch and commit, state and "rebuild pending". | [app.js:21-46](../src/astra_rag/static/app.js#L21-L46) → [routes.py:73-75](../src/astra_rag/routes.py#L73-L75) → [repos._view](../src/astra_rag/services/registry/repos.py#L56-L75) |
| 15 | `POST /api/search` with `{slug, query}` runs a hybrid search over that repo's collection. | [routes.py:96-100](../src/astra_rag/routes.py#L96-L100) → [pipeline.search](../src/astra_rag/services/ingestion/pipeline.py#L87-L95) |

At startup the app's lifespan runs [`registry.startup`](../src/astra_rag/services/registry/__init__.py#L6-L9): it brings
the database schema up to date and marks runs a previous process left `queued`/`running` as `failed`
([`__init__.py:13-16`](../src/astra_rag/__init__.py#L13-L16)).

**Errors:** any user-facing failure raises `AppError(message, status)` ([errors.py](../src/astra_rag/services/errors.py#L1-L7)).
One handler turns it into `{"ok": false, "error": "..."}` with that status
([`__init__.py:24-26`](../src/astra_rag/__init__.py#L24-L26)).

**Layering (who is allowed to talk to what):**

```
routes.py  (thin HTTP layer)
   |-- services/connections.py       -> connect flow and branch changes (uses everything below)
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
| Skipped files shown in the UI | [app.js:61-70](../src/astra_rag/static/app.js#L61-L70) (`skipped <path>: <reason>`) |
| Skipped files in the status API | [pipeline.py:20](../src/astra_rag/services/ingestion/pipeline.py#L20), [pipeline.py:57-59](../src/astra_rag/services/ingestion/pipeline.py#L57-L59) |

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
| Fix branch name in docs | ✅ at the time, but has drifted again (see [§12](#12-open-items-gaps-and-doc-drift-found-during-this-review)) |
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
| Qdrant collection | `astra__<slug>` (unsafe characters turned into `_`) | [store.py:17-18](../src/astra_rag/services/ingestion/store.py#L17-L18) |
| Ingestion status | in-memory dict keyed by slug in P1; **since P4** the `repo_slug` column of the SQLite `ingestion_runs` table | [db.py:37-56](../src/astra_rag/services/registry/db.py#L37-L56), [runs.latest_run](../src/astra_rag/services/registry/runs.py#L77-L81) |
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
| Routes take the slug | [routes.py:31-36](../src/astra_rag/routes.py#L31-L36) (`SearchRequest.slug`), [routes.py:65](../src/astra_rag/routes.py#L65), and since P4 [routes.py:78-79](../src/astra_rag/routes.py#L78-L79) |
| UI polls by slug | [app.js:72-76](../src/astra_rag/static/app.js#L72-L76) |

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
| [test_routes.py:52](../tests/test_routes.py#L52) `test_clone_queues_a_persisted_run_on_the_default_branch` (was `test_clone_queues_ingestion_with_commit_and_status_is_readable` before P4) | Response carries `slug: github.com__acme__golden`; status is readable by slug. |

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
| `head_sha(branch)` | Current commit of a branch. | since P4: checks a branch exists (connect, settings); P5 will compare heads |
| `default_branch()` | Repo's default branch. | since P4: tracked branch of a newly connected repo |
| `clone(dest, branch)` | Shallow clone. | cloner |
| `is_ancestor(base, head)` | Is `base` contained in `head`? | not yet (P5) |
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
| [test_routes.py:21-28](../tests/test_routes.py#L21-L28) | In P2 the route tests patched `routes.adapter_for` instead of `github_client`, assertions unchanged. Since P4 they patch `services.connections.adapter_for` ([test_routes.py:19](../tests/test_routes.py#L19)). |

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

## 7. Extra change shipped with P3: token saved as soon as the host accepts it

Not a plan item, but it is in commit `4607ba9` and listed separately in the CHANGELOG.

- **Before:** the PAT was saved to `.env` only after a successful clone.
- **After:** it is saved right after the root listing succeeds, before the structure check and clone
  ([routes.py:50-52](../src/astra_rag/routes.py#L50-L52)). So a repo that fails validation (422) or whose clone fails
  still has its token saved, and a blank token field works next time. A token the host rejected is never saved,
  because `list_dir` raises before the save line.
- The 422 body now includes `token_saved` ([routes.py:55-59](../src/astra_rag/routes.py#L55-L59)), and the UI clears the
  token field and says "(token saved for this repository)" ([app.js:106-108](../src/astra_rag/static/app.js#L106-L108)).
- `CLAUDE.md`'s security rule was updated to describe this.
- Tests: [test_routes.py:70](../tests/test_routes.py#L70) (saved even if clone fails),
  [:136](../tests/test_routes.py#L136) (rejected token not saved),
  [:87](../tests/test_routes.py#L87) (missing structure saves token, no ingestion started).

---

## 8. Work done before the phases (W0, W1) that P0-P3 build on

These were done before `plan/phases.md` existed. They are summarised so you can trace the full flow.

### W0: connector (2026-10-26)
URL parse, root listing, structure validation, clone. Now spread across `registry`, adapters, `validator`, `cloner`.

### W1: RAG ingestion pipeline (2026-10-27)

| Step | What | Where |
|---|---|---|
| Load | Walk `project-data/`; load `.md/.markdown/.txt/.csv/.docx`; skip hidden, unsupported, empty, >25 MB, unreadable; docx → markdown via `markitdown`; sha256 per file. | [loader.py](../src/astra_rag/services/ingestion/loader.py), types in [config.py:49-51](../src/astra_rag/config.py#L49-L51) |
| Chunk markdown | Split by heading with a breadcrumb path; code fences and tables kept whole if they fit; oversize tables repeat header rows; very long lines cut into overlapping word windows; headings never end a chunk; tiny last chunk folded back. Line ranges tracked. | [md_chunker.py](../src/astra_rag/services/ingestion/md_chunker.py) |
| Chunk CSV | Auto-detect delimiter; one summary chunk (columns, row count, first 3 rows) + row-group chunks with the column header repeated; row ranges tracked; capped at 100k rows with a warning. | [csv_chunker.py](../src/astra_rag/services/ingestion/csv_chunker.py) |
| Token budget | Cheap, slightly pessimistic token estimate; target 380, cap 480 (below bge's 512). | [tokens.py](../src/astra_rag/services/ingestion/tokens.py), [config.py:42-47](../src/astra_rag/config.py#L42-L47) |
| Metadata | Every chunk payload: repo, repo_slug, host, owner, branch, commit_sha, path, filename, folder_parts, folder_top, file_type, file_hash, title, chunk_id, chunk_index, chunk_kind, heading_path, line or row range, `source_url` (from adapter), text. `chunk_id = sha1(path, index, sha1(text))`. | [chunker.py:14-58](../src/astra_rag/services/ingestion/chunker.py#L14-L58) |
| Embed | Local `fastembed`: dense `BAAI/bge-base-en-v1.5` (768-d) + sparse `Qdrant/bm25`, batches of 32. Text embedded = breadcrumb + chunk text. | [embedder.py](../src/astra_rag/services/ingestion/embedder.py), [chunker.py:56-58](../src/astra_rag/services/ingestion/chunker.py#L56-L58) |
| Store | Qdrant collection `astra__<slug>`, dropped and recreated each ingest; named vectors `dense` (cosine) + `sparse` (IDF); keyword indexes on path, folder_top, file_type, file_hash, commit_sha; point id = UUIDv5(chunk_id). | [store.py:17-56](../src/astra_rag/services/ingestion/store.py#L17-L56) |
| Search | Hybrid: dense + sparse prefetch (3× limit, min 20), fused with RRF; optional `folder_top` / `file_type` filters. Missing collection → 404. | [store.py:61-90](../src/astra_rag/services/ingestion/store.py#L61-L90) |
| Status | In-memory per slug: queued/running/done/failed, counts, skipped files, warnings, error, timestamps. Never raises; errors are recorded. | [pipeline.py:16-65](../src/astra_rag/services/ingestion/pipeline.py#L16-L65) |

---

## 9. Security controls: where each one is enforced

| Rule (from `CLAUDE.md`) | How it is enforced | Where | Test |
|---|---|---|---|
| PAT stored only in git-ignored `.env` | `token_store` writes `.env`; `.env` and `.env.*` are in `.gitignore` | [token_store.py:95-103](../src/astra_rag/services/token_store.py#L95-L103), [.gitignore](../.gitignore) | [test_token_store.py](../tests/test_token_store.py) |
| PAT saved only after the host accepted it | save is after `list_dir("")` succeeds | [routes.py:50-52](../src/astra_rag/routes.py#L50-L52) | [test_routes.py:136](../tests/test_routes.py#L136) |
| `.env` never half-written | write to temp file, then `os.replace`; `chmod 600` where supported | [token_store.py:77-92](../src/astra_rag/services/token_store.py#L77-L92) | n/a |
| PAT never returned by any API | responses only carry `token_saved` / `token_reused` booleans | [routes.py:57-62](../src/astra_rag/routes.py#L57-L62) | [test_routes.py:29](../tests/test_routes.py#L29) |
| PAT never in repr/str/logs | `PatCredential` redacted, `__slots__` | [credentials.py:9-23](../src/astra_rag/services/sources/credentials.py#L9-L23) | [test_credentials.py](../tests/sources/test_credentials.py) |
| PAT never in URL, `.git/config` or process args | header passed via `GIT_CONFIG_*` env vars | [git.py:12-24](../src/astra_rag/services/sources/git.py#L12-L24) | [test_git.py:25](../tests/sources/test_git.py#L25), [contract.py:116](../tests/sources/contract.py#L116) |
| PAT cleared from the page | UI blanks the field after success or a 422 with `token_saved` | [app.js:101](../src/astra_rag/static/app.js#L101), [app.js:107](../src/astra_rag/static/app.js#L107) | n/a (manual) |
| Error messages safe to show | `AppError` only; host body never included | [sources/errors.py](../src/astra_rag/services/sources/errors.py), [`__init__.py:24-26`](../src/astra_rag/__init__.py#L24-L26) | [contract.py:84](../tests/sources/contract.py#L84) |
| Repo cannot pull outside files into the index | loader link checks + `core.symlinks=false` | [loader.py:37-42](../src/astra_rag/services/ingestion/loader.py#L37-L42), [git.py:23](../src/astra_rag/services/sources/git.py#L23) | [test_ingestion.py:119-152](../tests/test_ingestion.py#L119-L152) |
| Hosts' tokens kept apart | host-aware slug keys | [repo_ref.py:20-23](../src/astra_rag/services/repo_ref.py#L20-L23) | [test_token_store.py:44](../tests/test_token_store.py#L44) |
| Clones and vector data not committed | `temp_storage/*`, `.cache/` git-ignored; Qdrant data in a Docker volume | [.gitignore](../.gitignore), [docker-compose.yml](../docker-compose.yml) | n/a |
| Blocking I/O off the event loop | routes are plain `def` (FastAPI runs them in a worker thread) | [routes.py:40-42](../src/astra_rag/routes.py#L40-L42) | n/a |

---

## 10. Reference: endpoints, config, stored data, dependencies

### Endpoints

| Method + path | Body / params | Returns | Code |
|---|---|---|---|
| `GET /` | none | the HTML page | [routes.py:39-44](../src/astra_rag/routes.py#L39-L44) |
| `POST /api/validate-and-clone` | `{url, token}` (blank token = use saved) | 200 `{ok, message, path, commit_sha, token_saved, token_reused, ingestion:{slug, state}}`; 422 `{ok:false, missing[], token_saved, error}`; other errors `{ok:false, error}` | [routes.py:48-62](../src/astra_rag/routes.py#L48-L62) |
| `GET /api/ingestion-status/{slug}` | slug | `{ok, state, commit_sha, collection, files_loaded, files_skipped[], chunks_total, chunks_stored, warnings[], error, started_at, finished_at}`; 404 if never started | [routes.py:65-70](../src/astra_rag/routes.py#L65-L70) |
| `POST /api/search` | `{slug, query, limit=8 (1-50), folder?, file_type?}` | `{ok, results:[payload + score]}` | [routes.py:96-100](../src/astra_rag/routes.py#L96-L100) |
| `GET /docs` | none | FastAPI OpenAPI UI | built in |

### Config ([config.py](../src/astra_rag/config.py))

| Setting | Value | Line |
|---|---|---|
| `REQUIRED_FILES` / `REQUIRED_FOLDERS` | `policies.md`, `nomenclature.md` / `project-data`, `templates` | [12-13](../src/astra_rag/config.py#L12-L13) |
| `SUPPORTED_HOST_KINDS` | `github`, `ghe`, `azure_devops` | [16](../src/astra_rag/config.py#L16) |
| `GIT_TIMEOUT_SECONDS` / `HTTP_TIMEOUT_SECONDS` | 300 / 20 | [18-19](../src/astra_rag/config.py#L18-L19) |
| `QDRANT_URL` / `QDRANT_API_KEY` | env, default `http://localhost:6333` | [33-34](../src/astra_rag/config.py#L33-L34) |
| Models | `BAAI/bge-base-en-v1.5` (768), `Qdrant/bm25` | [37-39](../src/astra_rag/config.py#L37-L39) |
| Chunk sizes | target 380, max 480, min 100, overlap 50 | [43-46](../src/astra_rag/config.py#L43-L46) |
| File limits | 25 MB, 100k CSV rows | [50-51](../src/astra_rag/config.py#L50-L51) |
| `ENV_FILE` | `<repo root>/.env` | [52](../src/astra_rag/config.py#L52) |

### What is stored where

| Data | Location | Survives restart? | Keyed by |
|---|---|---|---|
| Repo URL + PAT | `.env` at repo root (git-ignored) | yes | `ASTRA_REPO_<SLUG>_URL/_TOKEN` |
| Cloned repo | `temp_storage/<slug>/` (git-ignored) | yes, replaced on reconnect | slug |
| Chunks + vectors | Qdrant collection `astra__<slug>` in Docker volume `qdrant_storage` | yes | slug |
| Ingestion status | Python dict in memory | **no** (P4 moves it to SQLite) | slug |
| Embedding models | `.cache/fastembed` (git-ignored) | yes | model name |

### Dependencies ([pyproject.toml](../pyproject.toml))
`fastapi`, `uvicorn[standard]`, `jinja2`, `qdrant-client`, `fastembed`, `markitdown[docx]`; dev: `httpx` (for
FastAPI's `TestClient`). P0-P3 added **no new dependencies**; host REST calls use the standard library `urllib`.

---

## 11. Test inventory

Run: `uv run python -m unittest discover -s tests -t .` → **105 tests, OK, 1 skipped** (2026-10-28).

| File | Covers | Phase(s) |
|---|---|---|
| [tests/test_ingestion.py](../tests/test_ingestion.py) | loader (incl. symlinks), md and CSV chunkers, metadata, pipeline end to end on in-memory Qdrant with a fake embedder | W1, P0, P1 |
| [tests/test_routes.py](../tests/test_routes.py) | the three API routes with a fake adapter | P1, P2, P3 |
| [tests/test_token_store.py](../tests/test_token_store.py) | save/get/forget, host separation, legacy migration | P1 |
| [tests/test_validator_and_url.py](../tests/test_validator_and_url.py) | structure check, URL parsing, host-aware slugs | W0, P1 |
| [tests/test_cloner.py](../tests/test_cloner.py) | clone folder naming, replacement, branch pass-through | P1, P2 |
| [tests/sources/contract.py](../tests/sources/contract.py) | shared adapter contract (10 tests per adapter) | P2 |
| [tests/sources/fake_http.py](../tests/sources/fake_http.py) | fake `urlopen` used by contract tests | P2 |
| [tests/sources/test_github.py](../tests/sources/test_github.py) | GitHub contract + specifics | P2 |
| [tests/sources/test_azure_devops.py](../tests/sources/test_azure_devops.py) | ADO contract + URL parsing + specifics | P3 |
| [tests/sources/test_git.py](../tests/sources/test_git.py) | shared clone helper | P0, P2 |
| [tests/sources/test_credentials.py](../tests/sources/test_credentials.py) | `PatCredential` redaction | P2 |
| [tests/sources/test_registry.py](../tests/sources/test_registry.py) | adapter dispatch, config/registry agreement | P2, P3 |
| [tests/fixtures/repo/project-data/](../tests/fixtures/repo/project-data/) | sample md, txt, csv, empty csv, png | W1 |

No test uses the network or a real token. Qdrant tests use `QdrantClient(":memory:")`; embeddings use a fake embedder.

---

## 12. Open items, gaps and doc drift found during this review

### Open from the plan (already known and recorded)
1. **P3 acceptance not run:** no real Azure DevOps repo has been connected yet. Three things to check when it is:
   - the citation link's line highlighting (`lineEnd = end + 1` with column 1) lands on the right lines;
   - whether ADO lists root names in their real case (our validator enforces exact case either way);
   - `is_ancestor` via `diffs/commits` `behindCount` gives the expected answer (not used by any route yet).
2. **P0 acceptance on Windows:** the symlink test is skipped on this machine. The CHANGELOG says it was verified on
   Linux in Docker.
3. **Adapter methods not wired in yet:** `read_file`, `head_sha`, `default_branch`, `is_ancestor` are implemented and
   tested, but no route calls them. This is expected; P4, P5, P7 and P9 will use them.

### Doc drift spotted while writing this (not fixed here)
1. **Branch name:** current branch is `goldan-repo-re-guru`. [CURRENT_STATE.md](CURRENT_STATE.md) says `goldan-repo-re`
   and [CLAUDE.md](../CLAUDE.md) says `goldan-repo`.
2. **README security note is stale:** [README.md](../README.md) still says the token is saved "after a successful
   connect" under key `ASTRA_REPO_<OWNER>__<NAME>_TOKEN`. Since P1 the key includes the host
   (`ASTRA_REPO_<HOST>__<OWNER>__<NAME>_TOKEN`), and since the P3-era change it is saved once the host accepts it.
3. **`pyproject.toml` description** still says "Connect a GitHub repo"; ADO is supported now.
4. **README structure block** says `routes.py` is "page + POST /api/validate-and-clone" but it also serves the status
   and search endpoints.

### Small code observations (no action required for P0-P3)
1. **Any unknown host is treated as GitHub Enterprise** ([repo_ref.py:35](../src/astra_rag/services/repo_ref.py#L35)).
   A self-hosted GitLab on a name not starting with `gitlab.` would be sent to the GitHub adapter and fail with a
   GitHub-flavoured error. Acceptable now; worth revisiting in P10.
2. **`_field` is duplicated** in [github.py:91-97](../src/astra_rag/services/sources/github.py#L91-L97) and
   [azure_devops.py:141-147](../src/astra_rag/services/sources/azure_devops.py#L141-L147) with only the label
   different. It could move to a shared helper.
3. **Ingestion status is in memory**, so a restart loses it (planned for P4).
4. **Re-ingest drops the live collection first** ([store.py:35-45](../src/astra_rag/services/ingestion/store.py#L35-L45)),
   so search is empty while a rebuild runs (planned for P5, alias swap).

---

## 13. How to verify this yourself

```powershell
# 1. See exactly what each phase changed
git show --stat f7ed92a   # P0
git show --stat 764eb13   # P1
git show --stat e994236   # P2
git show --stat 4607ba9   # P3
git show 4607ba9 -- src/astra_rag/services/sources/azure_devops.py

# 2. Run all tests (no network or tokens needed)
uv run python -m unittest discover -s tests -t .

# 3. Run one phase's tests
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
