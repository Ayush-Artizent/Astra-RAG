# Code plane: Phase 0 spike report

Audience: the reviewer, then the orchestrator and control-plane leads.
Status: draft for review. Covers tasks S1 to S7 of [codegraph-work-plan.md](codegraph-work-plan.md).
Design references use the IDs of the ASTRA RAGaaS Architecture Design, Revision 3.

## 1. Summary

The design holds. CodeGraph 1.6.2, used unmodified, can serve as the code plane: queries run from the
library, indexing runs as a CLI child process, and queries keep working while a sync runs. Three things
changed our plan:

1. **Sync time depends on repo size, not on change size.** About 1 minute on a 3,000-file repo for any change.
2. **Symbol names are ambiguous** (9 to 11 percent of names), and the library's qualified form is `Class::method`.
3. **Bootstrap is heavy**: about 7 minutes and 2 GB of memory for a 3,000-file repo.

Decision needed from the reviewer: the index-lag target per repo size (Q2). See section 6.

## 2. Setup and limits of this evidence

- Machine: one Windows 11 laptop. Node v24.20.0. CodeGraph `@colbymchenry/codegraph` 1.6.2 from npm, pinned.
  The package bundles its own Node v24.16.0 for the CLI.
- Repos: a copy of CodeGraph's own source (TypeScript, 297 files indexed) and Django at commit `36920bb`
  (Python, 3,024 files, shallow clone).
- Each measurement is a single run unless stated. Cold-cache runs are slower than warm ones, and I could not
  isolate antivirus or disk effects (no Defender settings were changed).
- Not tested: Linux, Node 22, repos above 3,000 files, concurrent writers, `readOnly` open during a write,
  more than one adapter process.
- Scripts and logs: `code-adapter/spikes/` (`s1_s3_s5.cjs`, `s3b.cjs`, `s4.cjs`, `s2_sync_timing.ps1`,
  `s2b_lib_sync.cjs`, `s5b_untested_calls.cjs`, `index_django_timed.log`).

## 3. Results

### S1: WAL and Node 24 (A4)

| Check | Result |
|---|---|
| Library opens a CodeGraph DB on Node 24.20 on Windows | Pass |
| Index DB `journal_mode` | `wal` |
| In-memory scratch DB `journal_mode` | `memory` |

The startup probe must open a **file-backed** scratch DB. An in-memory DB would report `memory` and fail the
check wrongly. The npm package ships its own Node 24.16 for the CLI, so the adapter's Node version only
affects the library, not indexing.

### S2: timings

| Repo | Operation | Result |
|---|---|---|
| TS (297 files) | init + index | 5.9 s reported |
| Django (3,024 files) | init + index | 62,625 nodes, 192,616 edges, 174 MB DB, **449 s wall** (second run, timed phases) and 380 s (first run) |
| Django | no-op sync | 5.8 to 10.7 s |
| Django | sync, 1 changed file (first, cold) | 116 s |
| Django | sync, 5 and 50 changed files | 59 s and 60 s |
| Django | same 2-file sync through the library | 52 s, 318 MB RSS |
| CLI | `--version` warm / cold | 0.3 s / 4 s |
| CLI | `status` on Django | 4.7 s warm, 20.8 s cold |

Phase breakdown of the full Django index (449 s): CLI start 16 s, scanning 3 s, parsing 18 s, **resolving
397 s** (271k references), linking 9 s. The "10 s" and "20.7 s" that CodeGraph prints cover parsing only.
Memory in the main process reached about 2 GB, with 5 parse workers recycling at about 500 MB each.

Phase breakdown of a 2-file sync on Django (52 s): scanning 1 s, parsing 3 s, resolving about 16 s (72
references), **linking about 29 s**, finalizing about 3 s. Sync time was the same for 5 and 50 files, so the
resolve and link passes scale with the graph, not the change.

I did not find why resolving is slow. The log shows the WAL growing from 91 MB to 156 MB and stalls of about
45 s, which suggests SQLite write cost on this disk, but that is a hypothesis.

Library versus CLI: 52 s versus 59 s. No meaningful gain from replacing the child process.

### S3: `findPath` edge metadata (A5)

- Edges carry `provenance`. Empty means static (tree-sitter). `heuristic` marks synthesized edges
  (84 `calls` edges of 13,859 on the TS fixture).
- Heuristic edges carry metadata keys `synthesizedBy`, `registeredAt`, `via`, `event`. Example:
  `SqliteDatabase::prepare -> NodeSqliteAdapter::prepare`, `synthesizedBy: interface-impl`,
  `registeredAt: db/sqlite-adapter.ts:87`.
- `findPath` follows heuristic edges (tested on a direct heuristic hop).
- Without an edge-kind filter the search also walks other edge kinds. Flow mode must pass `['calls']`.
- Conclusion: flow mode uses `findPath` and the CLI `explore` fallback is not needed. A5 is resolved.

### S4: queries during a sync

40 files edited, `codegraph sync` run as a child process, 961 queries (`searchNodes` + `getStats`) from the
library on an open read-write handle during the 18 s wall-clock window: **0 errors**, p50 4.6 ms, p95 7.8 ms,
max 29.9 ms. The existing handle saw the new symbols after the sync. Not tested: `readOnly` open during an
active write, and queries during the long Django resolving or linking phases.

### S5: symbol resolution

| Finding | Evidence |
|---|---|
| Library qualified names use `::` | `CodeGraph::sync` |
| `getNodesByQualifiedName` is exact and fast | 0.1 to 12 ms. Works with `QuerySet::filter`. Returns 0 for `QuerySet.filter` |
| `searchNodes` ranks dotted names badly | For `QuerySet.filter` the real method ranked third behind `_filter_or_exclude` |
| Bare names are ambiguous | `filter`: three methods at 99.1. Names used by more than one symbol: 9 percent (TS), 11 percent (Django). Worst: `Meta` x1109, `__init__` x974 |
| Other calls | `getCode` 3 to 6 ms, `getCallees` 1 to 25 ms, `readOnly` open 0.3 to 1.1 s |

Resolution rule adopted in the contract: normalise `.` to `::`, try the exact qualified name, fall back to
search, and report `exact`, `fuzzy`, `ambiguous` or `not_found` with up to 5 alternatives.

### Other findings

- The CLI prints a telemetry notice. The adapter and its child processes must set `CODEGRAPH_TELEMETRY=0`
  (customer code).
- The library's score is "for relative ranking only" and is not normalised. The orchestrator fuses by rank
  (D7), so the score must not be used for fusion.
- The vendored source folder is named `.codegraph`, which is also CodeGraph's data directory name. Rename it
  before it causes confusion.

## 4. Decisions

| # | Decision | Basis |
|---|---|---|
| 1 | Keep the design: unmodified pinned package, library for queries, CLI child process for init, index, sync. | S1, S3, S4 |
| 2 | Flow mode via `findPath` with edge kind `calls`. No CLI `explore` fallback. | S3 |
| 3 | Sync stays a child process. | S2: library is not faster |
| 4 | Coalesce sync jobs per project to the newest SHA. | S2: about 1 minute per sync whatever the size |
| 5 | One bootstrap at a time per adapter, with a memory limit. | S2: about 2 GB, about 7 minutes |
| 6 | Resolution by exact `::` lookup, then search, with an ambiguity report. | S5 |
| 7 | Startup probe uses a file-backed DB. | S1 |
| 8 | Telemetry off everywhere. | CLI output |
| 9 | Contract v0 as drafted in `contracts/code-adapter.openapi.yaml`. | S6 |

## 5. Consequences for the work plan

- Add: sync coalescing and a bootstrap lock to L2 and L3.
- Add: ambiguity handling and the `resolved_symbols` response to A6.
- Remove: the CLI `explore` fallback in L6.
- L3 and L5: report `phase` (scanning, parsing, resolving, linking) in the job status, so that long runs are
  visible. Bootstrap needs a long timeout (tens of minutes for large repos).
- H4: add an index-lag measurement on a repo of the real customer size.

## 6. Open items

| # | Item | Needed from |
|---|---|---|
| Q2 | Index-lag target by repo size. The design says under 2 minutes after a push. Django measured about 1 minute warm and 2 minutes cold, and larger repos will be slower. Proposal: 2 minutes for up to 1,000 files, 5 minutes up to 5,000, measure beyond that. | Reviewer |
| 1 | Cause of slow resolving and linking. Check whether it also happens on Linux, and whether any CodeGraph setting reduces it. | Spike follow-up (about 1 day) |
| 2 | `readOnly` open during an active sync, and query latency during the Django resolving and linking phases. | Spike follow-up (about 0.5 day) |
| 3 | A representative customer repo, or a size range. | Product or platform |
| Q1 | Repo hosting and credentials. | Product or platform |
| Q3 | Symbol cross-links at launch. | Reviewer |

## 7. Recommendation

Proceed to Phase 1 with the decisions above. Run open items 1 and 2 in parallel with the adapter skeleton,
because they affect only limits and timeouts, not the contract.
