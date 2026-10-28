# Code plane work plan: CodeGraph adapter

Audience: engineers on the code plane, and the orchestrator and doc-ingest leads who depend on it.
Source design: ASTRA RAGaaS Architecture Design, Revision 3. IDs (F, N, A, D, Q) refer to that document.

## 1. Goal and scope

Deliver the **code plane** of the RAG service: a Node adapter around the published CodeGraph package that
the Python orchestrator calls over HTTP. MVP runs as separate local processes (no Docker or Kubernetes).

In scope: adapter service, tenant path mapping, symbol resolution, response shaping, SHA-driven index
jobs, orchestrator client, isolation and contract tests, eval.
Out of scope: document plane, gateway, control plane, Qdrant, embedding, any change to CodeGraph itself.

## 2. Decisions already made

| # | Decision | Basis |
|---|---|---|
| 1 | Adapter is a Node microservice. The orchestrator is Python and calls it over HTTP. | Doc-ingest is Python, CodeGraph is Node. HTTP contract is the boundary. |
| 2 | Use the **npm package, pinned to one version, unmodified**. | A4, D6. |
| 3 | **Library** for queries, **CLI as a child process** for `init`, `index`, `sync`. | A5; sync is synchronous and must not block queries (review finding 4). |
| 4 | Do **not** drive the MCP server. | Output is agent-oriented markdown, one process per project. |
| 5 | MVP stand-ins: SQLite job table, local `./data` folders, single adapter process, dev signing key. | No Docker or K8s access. |
| 6 | Existing CodeGraph features are reused, not rebuilt: incremental `sync()`, `getChangedFiles`, `indexAll`, search, callers, impact, `findPath`, `getStats`. | Checked in `src/index.ts`. |

## 3. What we build (the gap)

1. HTTP service surface (upstream only has a loopback UI server and a local MCP socket).
2. Symbol-name to node-id resolution (the library takes node ids, our API takes names).
3. Tenant mapping: envelope to `/data/{org}/{project}/` with one path-building function.
4. Response shaping: citation string, provenance, `commit_sha`, `index_time`, `flow` array, 422 rules.
5. SHA-driven bootstrap and sync jobs, plus a reconcile job.
6. Isolation, contract and eval tests.

## 4. Proposed layout

```
code-adapter/
  src/
    server.ts          HTTP server, routing, error mapping (problem+json)
    envelope.ts        HMAC verify, claims, request_id
    paths.ts           the one path builder (org, project) -> directory; traversal refused
    projects.ts        open/close handles, LRU of CodeGraph instances per project
    resolve.ts         symbol name -> node id (ambiguity and not-found handling)
    modes/             lookup.ts, flow.ts, callers.ts, impact.ts
    shape.ts           node/edge -> provenance, citation, flow hops
    validate.ts        per-mode validation, error_code table
    jobs/              intake.ts, bootstrap.ts, sync.ts, reconcile.ts
    status.ts          GET status
  test/                unit, contract, isolation
contracts/
  code-adapter.openapi.yaml   single source for TS types and Python pydantic models
```

Note: the vendored upstream source currently sits in a folder named `.codegraph`. That is also the name of
CodeGraph's data directory, which it skips when indexing. Rename the vendored folder (for example
`vendor/codegraph-src`) and keep it as reference only, not part of the build.

## 5. Work breakdown

Estimates are ideal days for one engineer and are first-pass. Re-plan at the end of week 1.

### Phase 0: Spikes and contract (week 1)

| ID | Task | Est | Done when |
|---|---|---|---|
| S1 | Install pinned package. Run on Windows with Node 24.20. Open a scratch DB, confirm `journal_mode = wal` (A4). | 0.5 | Probe passes, or decision to pin Node 22 LTS. |
| S2 | Index 2-3 repos (small, medium, largest available). Record index time, sync time, DB size, memory. | 1 | Numbers in the spike report. |
| S3 | `findPath`: does it return edges with metadata (provenance, registration site)? Does it follow synthesized edges? (A5) | 1 | Go or no-go for flow mode via `findPath`; fallback is CLI `explore`. |
| S4 | Run queries from the library while `codegraph sync` runs as a child process on the same project. | 0.5 | No errors, no stalls beyond a set threshold. |
| S5 | Symbol resolution probe: how does `searchNodes` rank an exact qualified name versus a bare name? How common are ambiguous names? | 1 | Rules for resolving `TokenService.issue` and `login` to ids. |
| S6 | Draft the OpenAPI contract with the orchestrator lead (request, response, errors, envelope header). | 1.5 | Contract v0 reviewed and agreed. |
| S7 | Spike report. | 0.5 | Written, shared. |

Exit gate: S1, S3 and S6 resolved. Otherwise week 2 scope changes.

### Phase 1: Adapter skeleton (week 2)

| ID | Task | Est | Done when |
|---|---|---|---|
| A1 | HTTP server, routing, problem+json errors (401, 404, 413, 422, 429, 503). | 1 | Health and unknown-route tests pass. |
| A2 | `envelope.ts`: verify HMAC envelope, expiry, lifetime cap of 5 minutes, 30 s skew. Tampered or expired returns 401. | 1 | Unit tests per control in section 6 of the design. |
| A3 | `paths.ts`: build `/data/{org}/{project}` from the envelope only. Reject traversal and separators in ids. | 0.5 | Traversal tests pass on Windows and POSIX styles. |
| A4 | `projects.ts`: open and cache CodeGraph handles, LRU, close on idle. Project not indexed yet returns `not_ready`, not an error. | 1 | Two projects served concurrently. |
| A5 | `validate.ts`: mode table (lookup, flow, callers, impact), depth 1 to 5, defaults 1 and 3, `error_code` values. Unknown fields return 422 naming the field. | 1 | Table-driven tests match design section 7. |
| A6 | `resolve.ts` using the S5 rules. Ambiguous names return the best match and record alternatives. Not found goes to the response as an unresolved symbol, not a failure. | 1.5 | Tests with duplicates, partial names, wrong case. |
| A7 | `modes/lookup.ts` and `modes/callers.ts`, `modes/impact.ts`. | 2 | Results correct on a fixture repo. |
| A8 | `shape.ts`: file, lines, symbol, qualified name, kind, `commit_sha`, `index_time`, citation string (`path:start-end (Qualified.name @sha)`). | 1 | Golden-file tests on the fixture repo. |
| A9 | `status.ts`: state, `last_synced_sha`, files, symbols, `last_sync`. | 0.5 | Matches design status example. |

### Phase 2: Index lifecycle (week 3)

| ID | Task | Est | Done when |
|---|---|---|---|
| L1 | Job table (SQLite) and intake: `code.bootstrap`, `code.sync` with envelope and SHA. Reject messages whose org does not match the project. | 1 | Swapped `org_id` is rejected. |
| L2 | Bootstrap: shallow clone, `init`, `index`, record counts. Clone auth depends on Q1. | 2 | New project becomes queryable. |
| L3 | Sync: fetch, reset to SHA, `codegraph sync` as a child process, then write `last_synced_sha` and time. Serialize per project. Idempotent re-run. | 2 | New SHA changes results. Query during sync still answers. |
| L4 | Timeouts, kill and cleanup of stuck child processes, error state with message. | 1 | Killed sync leaves the previous index usable. |
| L5 | Reconcile: compare `last_synced_sha` with branch head, queue a sync. Rebuild from git if the DB is missing or corrupt. Handle force-push and branch change. | 1.5 | Missed webhook recovered. Deleted data dir rebuilt without manual steps. |
| L6 | `modes/flow.ts` from the S3 outcome: `findPath` between consecutive symbols with edge provenance, or the CLI `explore` fallback. Result caps. | 2 | `flow` array matches design section 7, heuristic hops included. |

### Phase 3: Integration (week 3 into 4)

| ID | Task | Est | Done when |
|---|---|---|---|
| I1 | Generate TS types and pydantic models from the OpenAPI file. CI check that both are current. | 0.5 | Generation script runs in CI. |
| I2 | Python client for the adapter (owned with the orchestrator lead). 2 s plane deadline, map timeout and not_ready to `plane_status`. | 1.5 | Orchestrator returns docs results when the adapter is down. |
| I3 | Contract tests run from Python against a live adapter. | 1.5 | Pass on every endpoint and mode. |
| I4 | Launcher: one command starts all processes. | 0.5 | Fresh machine to running stack by script. |
| I5 | If Q3 is yes: lookup by exact symbol name for chunk cross-references. | 1 | `cross_refs` filled both ways. |

### Phase 4: Hardening and eval (week 4)

| ID | Task | Est | Done when |
|---|---|---|---|
| H1 | Isolation suite: two orgs with identical project names, symbols and files. Zero cross-org results on every endpoint. Release gate. | 2 | Suite green in CI. |
| H2 | Negative tests: expired and over-lifetime claims, wrong key, project outside org returns 404 not 403, path traversal strings. | 1 | All return the documented status. |
| H3 | Logs and traces with `request_id` and `org_id`. Metrics: latency p50 and p95, sync duration, index lag. | 1 | Visible in logs. |
| H4 | Eval: recall of the right symbols and callers on real ASTRA stage prompts, structured versus fallback. Latency versus N3. | 2 | Report with numbers. |
| H5 | Runbook: start, stop, rebuild a project, rotate the dev key. | 0.5 | Reviewed by the orchestrator lead. |
| H6 | Buffer. | 2 | Used for slippage. |

## 6. Timeline

| Week | Phases | Milestone |
|---|---|---|
| 1 | Phase 0 | Spike report and agreed contract. |
| 2 | Phase 1 | `lookup`, `callers`, `impact` work for a local repo through the adapter. |
| 3 | Phase 2, start of Phase 3 | Bootstrap and sync by SHA. Flow mode. |
| 4 | Phase 3, Phase 4 | Orchestrator returns merged code and docs. Isolation suite green. Eval report. |

Total about 3-4 weeks for one engineer on the critical path; the Python client (I2, I3) is shared with the
orchestrator team. Single engineer effort sums to roughly 35 ideal days, so with one engineer expect the
upper end or later.

## 7. Dependencies

| Need | From | By |
|---|---|---|
| Contract v0 agreed | Orchestrator lead | End of week 1 |
| Job table shape, project, org and repo binding record | Control plane owner | Week 3 |
| Repo access method and credentials (Q1) | Product or platform | Before L2 |
| Real stage prompts for eval | ASTRA team | Before H4 |
| Largest pilot repo for timings | Platform | Week 1 |

## 8. Risks

| Risk | Likelihood | Plan |
|---|---|---|
| Node 24 behaves differently from upstream's tested range | Medium | S1. Pin Node 22 LTS if needed. |
| `findPath` lacks edge metadata (A5) | Medium | CLI `explore` fallback. Contract unchanged. |
| Name resolution gives wrong symbol for ambiguous names | High | A6 returns alternatives. Callers should pass qualified names. Measure in H4. |
| Large repos make sync slow | Medium | Child process and WAL reads. S2 timings set limits before L2. |
| Windows paths or file locks | Medium | One path builder. WSL2 if blocked (A9). |
| Conceptual queries with no symbols retrieve poorly (F2) | High | `degraded` flag. Require keywords from callers. Measure in H4. |
| Upstream version drift | Low | Pin. Upgrade only when contract tests pass. |

## 9. Open questions

1. Q1: can a project have several repositories, and how are repos reached (GitHub App, GitLab, on-prem, archive)?
   MVP decided 2026-10-27: one repo per project, cloned over HTTPS with a token (section 12). Several repos per
   project, GitHub App installs and archives are still open.
2. What is the largest repo size in the pilot (files and size)?
3. Q3: are symbol cross-links required at launch?
4. Does the control plane owner provide the job table, or does the adapter keep its own for the MVP?
   Decided 2026-10-27: the adapter keeps its own SQLite file (section 12).

## 10. Definition of done

- Every code result carries `commit_sha`, a citation string, and edge provenance for flow hops.
- The isolation suite (H1) and contract tests (I3) pass in CI.
- A new project goes from registration to queryable with no manual steps.
- Eval and latency numbers are recorded against N3 and A7.
- Runbook reviewed.

## 12. Phase 2 decisions (2026-10-27)

Made by the reviewer to unblock Phase 2 (jobs, sync, flow). Each is the option recommended in the discussion.

| # | Question | Decision | Consequence |
|---|---|---|---|
| 1 | How do jobs reach the adapter? | HTTP endpoint, `POST /internal/v1/code/jobs` (already in the contract). | No queue to run for the MVP. A queue consumer can be added behind the same job code later. |
| 2 | Who owns the job record? | The adapter, in its own SQLite file in the data directory. | It holds job state, errors, idempotency keys and each project's repo binding (URL, branch, credentials reference). It does **not** hold the commit an index reflects: that is read from the index itself (row 6). Moving it to the control plane later means replacing one module. |
| 3 | How is the repo fetched? (Q1) | `git clone` over HTTPS with a token. The job carries `repo_url` and a `credentials_ref` that the adapter resolves from an environment variable or file. | One repo per project. GitHub App installs, several repos per project and uploaded archives are not covered and stay open. |
| 4 | Index-lag target? (Q2) | Scaled by repo size: 2 minutes up to 1,000 files, 5 minutes up to 5,000 files, measured case by case beyond. | Sets the sync timeout, the coalescing window and the reconcile interval. The thresholds are my proposal from one Django measurement, not a tested result. |
| 5 | Where does customer source live? | **A local working tree is kept next to the index** (`data/<org>/<project>/`), cloned shallow (depth 1). Ephemeral-tree and remote-only variants are deferred. | See 12.1. Customer source is at rest on our disks, so the hardening in 12.1 is a requirement of the clone step, not an option. |
| 6 | Where does `commit_sha` come from? | CodeGraph's own stamp, `indexed_at_commit` in the index's `project_metadata` table, not a record we write. **Adopted when Phase 2 started, for the reviewer to confirm.** | The stamp is written together with the index data, so it cannot name a commit the index does not reflect. Reading an internal table couples us to CodeGraph 1.6.2, so the version stays pinned and a test fails if the key disappears. See 12.2. |

Testing approach (not a reviewer decision): local git repositories created inside the tests, so cloning and syncing
are exercised with no network.

### 12.1 Source at rest: decision and consequences

**Decision (2026-10-27):** for the MVP the adapter keeps a shallow local clone of each project next to its index.
It is the only arrangement that works with CodeGraph unmodified (decision D6).

**Why the copy cannot be deleted after indexing** (spikes `s10`, `s9b`):
- `getCode` reads the source file from disk on every call. Without the tree, every result loses its text.
- A sync with the tree missing **deletes the project's symbols** from the index (the files look removed).
  `git checkout` followed by a sync repairs it.
- Syncing needs the tree. CodeGraph has no remote mode and never contacts a git host (no clone, fetch or pull).

**Disk (Django, 3,024 indexed files):** source tree 45 MB (CodeGraph reads 19 MB of it, 43%), `.git` 13 MB (depth 1),
index 179 MB. The copy of the source is about 58 MB, the index is the larger part. Plan about 5 times the working
tree per project, plus transient write-ahead log during a bootstrap (it reached 156 MB).

**Alternatives considered, not built:**

| Option | What it is | Why deferred |
|---|---|---|
| Ephemeral tree | Clone, sync, delete the tree. Serve snippets by reading git objects or the host API. | We would write our own snippet reader, every sync pays a fresh clone, and a kept `.git` is still source at rest. |
| Remote only | Nothing source-like on disk. Fetch each snippet from the git host per request. | Added latency, host API rate limits, one code path per host. The index still holds symbol names, paths and call structure, so "nothing at rest" is not achieved anyway. |

Either could be offered later for security-sensitive customers. Neither has been built or measured.

**Hardening required in the clone and sync steps** (design requirements; only the symlink mitigation has been tested):
1. **Symlinks.** Reading CodeGraph's source, the indexing read path follows in-repo symlinks out of the project
   (`allowSymlinkEscape`), while `getCode` refuses them. A malicious repo could put another tenant's symbol names and
   structure into its own index. This was **not reproduced** (no symlink rights on the Windows test account); a Linux
   test is needed. Mitigation tested on Windows: clone with `core.symlinks=false`, which writes a symlink entry as a
   plain text file, and the foreign symbol was not indexed. Persist the setting in the repo config, and scan the tree
   for real symlinks after checkout and refuse the project if any exist.
2. **Token.** Never put it in the URL or in `.git/config`. Pass it to git through environment variables for that one
   command, scoped to the repo host, and scrub it from stored errors.
3. **Repo-controlled behaviour.** No submodules, `GIT_ALLOW_PROTOCOL` limited to https, `GIT_TERMINAL_PROMPT=0`,
   user and system git config ignored. Never run `git clean` (it would delete `.codegraph`).
4. **Repo URL.** https only, no embedded credentials, no `file://`, loopback or private addresses (cloning an
   arbitrary URL is a server-side request), optional host allow list. `file://` is allowed only by a test-only setting.
5. **Cleanup.** Delete a failed or half-finished bootstrap and any stale lock. Delete the folder when a project is
   offboarded, after closing its handle (Windows cannot delete an open database). Run `git gc` periodically.
6. **Idle pruning.** Delete projects unused for a set time and rebuild on demand (Django bootstrap: about 7 minutes).

**Not covered here:** encryption at rest and folder permissions are an infrastructure decision. The repo-supplied
`codegraph.json` that CodeGraph reads has not been audited. Hardcoded credentials inside source files are returned in
snippets (CodeGraph returns only the key for config files, which I read but did not test); the design document has no
redaction requirement.

### 12.2 Commit tracking

CodeGraph writes the commit an index reflects as `indexed_at_commit`, after a full index and after every successful
sync. Tested in a throwaway git repo with our planned flow (shallow clone, `fetch <sha>`, `reset --hard <sha>`, sync)
(spike `s9b`, all checks passed): the stamp follows bootstrap, forward sync, rollback with deleted files, and a jump to
a commit that is not a descendant (rewritten history), and a no-op sync leaves it alone. This also means CodeGraph
already copes with force-pushes, so the reconcile job (L5) only compares the stamp with the remote branch head.
**Not tested:** what the stamp does if the process is killed mid-sync; CLI versus library; repos beyond Django's size.
The stamp is the HEAD of the git work tree that contains the project folder, so each project must be its own clone
root, and the clone step checks that.

## 13. Phase 2 status (2026-10-28)

Built and tested: L1 (job intake), L2 (bootstrap), L3 (sync) and most of L4 (failure handling). Not built: L5
(reconcile, `git gc`, idle pruning, disk report) and L6 (flow mode). 478 tests pass; typecheck is clean.

| Task | State | What exists |
|---|---|---|
| L1 job intake | Done | `POST /internal/v1/code/jobs`, `GET .../jobs/{id}`. A SQLite file holds jobs and each project's repo binding. One job per project, one bootstrap at a time, at most 2 jobs overall. Idempotency keys, scopes (`project:admin` for bootstrap, `code:sync` for sync), 409 on conflicts, queued syncs coalesced into the newest. |
| L2 bootstrap | Done | Shallow clone (`core.symlinks=false`, no submodules, only https, token through the environment), own-git-root and symlink checks, `codegraph init` as a child process, index check (complete, stamped with the checked-out commit). A failure deletes the folder and the repo record. |
| L3 sync | Done | Fetch the commit (by id, else the branch tip), `reset --hard`, `codegraph sync` as a child process, index check. A commit the index already reflects is skipped. If indexing fails the files are moved back to the indexed commit. `commit_sha` in every result now comes from the index. |
| L4 failure handling | Mostly done | Timeouts that kill the whole process tree, cancellation on shutdown (with a time limit), cleanup of half-made folders, rollback of a failed sync, and startup recovery for a job cut off by a crash. Not done: stale CodeGraph lock files (`codegraph unlock`) have never been seen in these tests. |
| L5 reconcile | Not started | Contract returns 501 for `reconcile`. |
| L6 flow | Not started | Query returns 501 for `flow`. |

**Behaviour added beyond the plan** (each is in the contract):
- `snapshot.sync_in_progress`, and `plane_status` `degraded` while it is true. A sync moves the files before the
  index catches up (about a minute on Django), so for that window snippets and line numbers may not match the
  commit. This is a consistency gap that exists by design of how CodeGraph reads files, not something we can remove.
- Status shows the active job and `indexing` while a bootstrap has no index yet.
- Citations show the commit shortened to 7 characters; the full commit is in `provenance.commit_sha`.
- Sync needs a full 40 or 64 character commit id.
- A job that failed is returned as is for a repeated Idempotency-Key, so a retry needs a new key.
- Repo URLs must be https, without credentials, not loopback or private addresses, and may be limited to a host
  allow list. `file://` is allowed only with a test-only setting (`ASTRA_ALLOW_FILE_REPOS=1`).
- Credentials: `credentials_ref` names an environment variable `ASTRA_REPO_TOKEN_<NAME>` holding a token or `user:token`.

**Found while building, and fixed:**
- Own-root check compared the long path git reports with Windows' short (8.3) temp path and rejected every
  bootstrap on this machine. It now compares real paths.
- The job store leaked an open file when it refused a newer schema. A cut-off bootstrap left a project stuck in
  "already being bootstrapped" forever; startup recovery now cleans it up.
- The OpenAPI file declared `phase` nullable but did not list `null` in its enum, so a strict validator rejected
  queued and failed jobs.

**Limits of the evidence:**
- Run on one Windows machine, with local `file://` repos, a tiny repo each. Nothing here touched a real git host,
  so token handling over https, redirects, and a host that refuses to fetch a commit by id are untested.
- On this machine git cannot create symlinks and falls back to plain files, so the symlink tests would pass even
  without our setting. They are regression guards for Linux, where the real leak is still unreproduced (checklist).
- Timings were never taken at scale: a Django-sized bootstrap and sync through these executors has not been run.
- Repo-URL checks do not resolve DNS, so a public name that points at a private address is not caught.
- The rate of `git` object growth over many syncs, and `git gc`, are unmeasured.

## 11. Checklist

Open decisions and measurements. Questions in section 9 and the open items in
[codegraph-spike-report.md](codegraph-spike-report.md) are tracked in their own documents.

- [ ] **Idle-project retention.** How long may an unused project stay on disk before it is deleted and rebuilt on demand? (12.1)
- [ ] **Secrets in snippets.** Does the platform need hardcoded credentials redacted before code is returned? The design document has no such requirement. (12.1)
- [ ] **Encryption at rest and folder permissions.** Who owns them, the platform team or this service? (12.1)
- [ ] **Symlink isolation on Linux.** Reproduce the cross-tenant symlink case with real symlinks (no symlink rights on the Windows test account). (12.1)
- [ ] **Confirm decision 6.** Read `commit_sha` from CodeGraph's own stamp. (12.2)
- [ ] **Stamp after a killed sync.** Not tested. (12.2)

- [ ] **Symbol discovery (to discuss).** How does the calling agent learn which symbols to send?
  - D3 says ASTRA stages must supply structured fields, but it doesn't say how a stage gets symbol names.
  - Routes today: the stage already has names; discover-then-drill-down (keyword `lookup`, then use returned qualified names); symbols named in retrieved doc chunks (needs Q3 cross-links); the orchestrator's rules-only analyzer (results marked `degraded`).
  - Gap: conceptual questions with no names or keywords retrieve poorly (F2, no code embeddings), and the contract has no way to browse or list symbols.
  - Decide: is keyword `lookup` plus drill-down enough, or do we add a discovery endpoint (file outline, top symbols under a path)?
  - Measure early: quality of keyword-only `lookup` on conceptual questions (not tested yet).
    - Partial finding, 2026-10-27 (`code-adapter/spikes/s8_keywords.cjs`, tiny repo and Django): full-text keyword search matches the start of a word. `token` finds `validate_token` but not `issueToken`, so it is weaker on camelCase code. Mitigation built: names that merely contain a keyword are added after the ranked matches (library `getNodesByNameSubstring`). Multi-word queries behave as OR. Conceptual queries ("password reset") return loosely related names (many unrelated `reset` methods), as expected without code embeddings. Not measured: precision and recall on real stage prompts.
  - Related: Q3, H4 (eval on real stage prompts).
