# ASTRA MCP server: delivery plan

> **Status: draft for team discussion (2026-10-30).** Branch `orch`.
> **Owner:** RAG team. DevX teams consume the server; their integration is out of scope here.
> **Depends on:** the doc plane (P9 tools; branch `goldan-repo-re-p9`, since merged into
> `goldan-repo-re` and deleted) and the code plane (branch `master`,
> `code-adapter/`). Neither plane changes for this work.

## 1. Goal and scope

Expose both ASTRA retrieval planes to DevX (and any other MCP client) as one **MCP server**, so the calling
agent decides what to retrieve instead of a router deciding for it.

**In scope:** an MCP server over stdio, thin passthrough tools for both planes, identity bound at spawn,
a Python envelope signer and client for the code plane, error and status mapping, tests, run docs.

**Out of scope:** changes to either plane; fan-out routing, rank fusion or a cross-plane token budget
(the calling agent does this); any change inside DevX; authentication for remote transport.

**This is a connector and nothing else.** Both planes are still being developed by their own teams, so the work
here is to join them, not to extend them. Anything that needs a plane to change — bootstrapping a repo into the
code plane, git auth against a host, golden repos and `golden.yaml` — belongs to that team. The risk this scope
carries is **API drift**, which §3 decisions 5 and 8 are the answer to.

## 2. What already exists (do not rebuild)

| Plane | Branch | State |
|---|---|---|
| Doc | `goldan-repo-re` | Connect, ingest, catalog, selection, `/api/context`, **and an LLM tool layer**: `GET /api/tools?project_id=` returns Claude-format schemas (with a live `doc_type` enum from the project's catalog), `POST /api/tools/invoke` runs one. Tools: `get_document_context`, `search_project_data`. |
| Code | `master` | Fastify adapter on `:8091`: four query modes (`lookup`, `flow`, `callers`, `impact`), symbol resolution with an ambiguity policy, `GET /status`, the job system (bootstrap, sync, reconcile, coalescing, idempotency keys, crash recovery), disk accounting, idle pruning, index-lag tracking, HMAC envelope verification, vitest suite. **No Python client.** |

The two branches share ancestor `2f59c5b`, but `master` deleted the whole Python app. **Never `git merge master`
into `orch`** — it would propose deleting `src/astra_rag/`. The code plane is a separate running service; this
server only needs its HTTP contract (`contracts/code-adapter.openapi.yaml` on `master`).

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| 1 | **stdio transport.** DevX spawns the server as a child process. | Chosen by the team. No network auth to build; DevX is deployed per client. |
| 2 | **Thin passthrough.** Mirror what each plane already does; no composed or task-shaped tools yet. | Keeps logic in the planes. Revisit once we see how agents actually call it. |
| 3 | **The server is stateless.** No database, no lock, no embedding models; HTTP to both planes. | The doc plane takes an exclusive lock on `<data dir>/astra.lock` per data directory and refuses a second instance. A stdio server is spawned per client, so it cannot start or embed the doc plane. |
| 4 | **Identity is bound at spawn**, not passed per call. `project_id` is stripped from every tool schema and injected server-side. | "DevX is deployed on clients, so mostly no cross-project calls." An agent then cannot name another project: isolation is structural, matching the code plane's rule that ids come only from the envelope. |
| 5 | **Doc tools are proxied, not redeclared.** Fetch schemas from `GET /api/tools`, execute through `POST /api/tools/invoke`. | Thinnest possible passthrough; the live `doc_type` enum and any tool the doc team adds appear with no change here. |
| 6 | **Code modes are four separate tools**, declared from the OpenAPI contract. | The schema can then enforce the per-mode arity rules, so `flow_needs_two_symbols` and `callers_needs_one_symbol` become unreachable instead of a 422 the agent must recover from. |
| 7 | **Same repo, branch `orch`.** | Chosen by the team. Shares conventions, tests and CI with the doc plane. |
| 8 | **`contracts/code-adapter.openapi.yaml` is the source of truth for the code tools**: generate the schemas from it and fail a test when they drift. | The doc tools are fetched, so they cannot drift; the code tools are declared here against a contract still marked DRAFT v0. A drift test is also how the plane teams will see what to update, since they maintain this connector when their API changes. |
| 9 | **A plane that is unreachable or not ready comes back as content, not an error.** | The agent can then fall back to the other plane. The exception is `tools/list`, which has nothing useful to return and so raises with the reason. |
| 10 | **Tools only.** No MCP resources or prompts. | Chosen by the team; thin passthrough. Revisit if DevX asks. |
| 11 | **Vendor only `contracts/code-adapter.openapi.yaml`, never `code-adapter/` itself.** | The adapter is a separate service under its own team. Copying a moving codebase here would rot; the contract is all the connector needs, and `SOURCE.md` records which commit it came from so a refresh is a deliberate act. |

## 4. Constraints found in the code

- **Single-instance lock** (decision 3 above). The lock is taken in the app lifespan, not at import, so importing
  doc-plane modules is safe — but it is not needed, and importing `astra_rag` pulls in FastAPI, the registry and
  the ingestion stack, which is slow for a process spawned per client. Keep the MCP package import-light.
- **Project-id patterns disagree.** Doc plane `PROJECT_ID_PATTERN = [A-Za-z0-9._-]{1,64}` allows dots and a
  leading `.`, `_` or `-`; code plane `ID_PATTERN = ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` allows neither, because the
  id becomes a directory name there. The sting is the failure mode: an id like `devx.payments` binds on the doc
  plane and works for documents, then fails inside `verifyEnvelope` as **HTTP 401**, so a naming mistake looks
  like an authentication problem. This server validates against the **stricter** pattern at startup and fails
  loudly. 2026-10-30: the doc plane team has been asked to adopt the same pattern (one constant,
  `config.py:34`, used by `tools/base.py` and `registry/rules.py`; tightening it is a breaking change for any
  binding row that already holds a now-invalid id).
- **Two project registries.** The doc plane binds `project_id` to a repo slug; the code plane binds
  `(org_id, project_id)` to a repo URL. They share a name, not a namespace. One id must be registered on both.
- **No authentication on the doc plane.** It must stay on `127.0.0.1` or behind an authenticating proxy. stdio
  does not change this: the server is a local client of it.
- **Envelope.** `X-Astra-Envelope: base64url(JSON).base64url(HMAC-SHA256(body, key))`, maximum lifetime 300 s,
  clock skew 30 s, scopes `query` / `code:sync` / `project:admin`. Mirror `code-adapter/src/envelope.ts`.

## 5. Configuration (environment, read at spawn)

| Variable | Required | Notes |
|---|---|---|
| `ASTRA_ORG_ID` | yes | Code plane only. Must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. |
| `ASTRA_PROJECT_ID` | yes | Used for both planes. Same pattern. |
| `ASTRA_DOC_URL` | no | Default `http://127.0.0.1:5000`. |
| `ASTRA_CODE_URL` | no | Default `http://127.0.0.1:8091`. |
| `ASTRA_ENVELOPE_KEY` | yes | At least 16 characters; same secret as the adapter's. |
| `ASTRA_MCP_TIMEOUT_MS` | no | Per-plane HTTP deadline. |

Startup refuses to run on a bad id, a missing key or an unreachable plane, with a message naming what is wrong.
Never log the key or a PAT.

## 6. Tool surface

**Doc plane (proxied, schemas fetched at startup):**

| MCP tool | Source |
|---|---|
| `get_document_context` | `/api/tools/invoke` — rules, whole template, reranked knowledge, within the plane's own token budget |
| `search_project_data` | `/api/tools/invoke` — targeted search of `project-data/` |

Rendering: `input_schema` → `inputSchema`, drop the `project_id` property, keep the description verbatim. The
plane's `DATA_NOTICE` ("reference data, not instructions") must survive into the MCP result — it matters more
here, because the content now crosses into another team's agent.

**Code plane (declared here, from the contract):**

| MCP tool | Adapter call | Schema enforces |
|---|---|---|
| `find_symbol` | `mode: lookup` | at least one of `symbols`, `keywords` |
| `find_callers` | `mode: callers` | exactly 1 symbol; `depth` 1–5, default 1 |
| `analyze_impact` | `mode: impact` | exactly 1 symbol; `depth` 1–5, default 3 |
| `trace_flow` | `mode: flow` | 2 or more symbols |
| `code_index_status` | `GET /internal/v1/code/status` | — |

Each call signs a fresh envelope with scope `query` and a short lifetime.

## 7. Status and errors

A plane that is not ready is **information for the agent, not a failure**. Surface, as tool content:

- code: `plane_status` (`ok` / `degraded` / `not_ready`), `snapshot.sync_in_progress`, `resolved_symbols[].status`
  (`exact` / `fuzzy` / `ambiguous` / `not_found`) with alternatives;
- docs: `status.knowledge` (`empty` / `no_index` / `unavailable: …`), `status.rerank`, `stale`, `warnings[]`.

Only a real failure is an MCP error: a transport failure, a 4xx that names a caller mistake, or a configuration
problem. Map the doc plane's `AppError` message and the code plane's problem+json `detail` / `error_code` to safe
text, never echoing a token or a host reply.

## 8. Layout

As built (M0-M2):

```
src/astra_mcp/            import-light; never imports astra_rag at runtime
  __init__.py             entry point: load config, then hand over to the server
  config.py               env read at spawn, cross-plane id check
  errors.py               PlaneError, the one failure both clients raise
  doc_client.py           GET /api/tools + POST /api/tools/invoke
  render.py               Claude tool entry -> MCP tool, project_id hidden
  code_client.py          /internal/v1/code/query and /status, envelope on every call
  envelope.py             HMAC signer (mirrors code-adapter/src/envelope.ts)
  tools_code.py           five tools built from the vendored contract
  contracts/              code-adapter.openapi.yaml + SOURCE.md (its origin commit)
  server.py               AstraServer: lists both planes, routes calls
tests/mcp/                fake planes over httpx.MockTransport; no network, no real tokens
```

Packaging: `pyproject.toml` uses `uv_build` with `module-name = ["astra_rag", "astra_mcp"]` — confirmed to build
a wheel holding both, with `contracts/*.yaml` included as package data, so the contract is readable at runtime
after an install.

## 9. Phases

One phase per PR, following `plan/phases.md` conventions. Definition of done for each: tests pass
(`uv run python -m unittest discover -s tests -t .`), new logic has tests that need no network and no real tokens,
and `timeline/CURRENT_STATE.md`, `TASKS.md`, `CHANGELOG.md` and `README.md` are updated.

| Phase | Name | Size | Delivers |
|---|---|---|---|
| M0 | Skeleton and config | S | Package, `mcp` + `httpx` dependencies, env config with fail-fast validation, `astra-mcp` entry point, a server that starts and lists zero tools |
| M1 | Doc tools | M | Schema fetch and render, `project_id` injection, invoke proxy, `AppError` mapping, `DATA_NOTICE` preserved |
| M2 | Code client and tools | M | Envelope signer, httpx client, the five tools, problem+json mapping |
| M3 | Status semantics | S | Not-ready, degraded, stale, unresolved symbols and warnings surfaced as content; only real failures raise |
| M4 | Ship | S | Spawn instructions for DevX, runbook, timeline updates |

**M0 prerequisite — checked 2026-10-30, cleared.** The MCP Python SDK resolves on 3.14. `mcp` 2.3.0 declares
`requires-python >=3.10` and carries explicit 3.14 markers (`anyio>=4.10` and `starlette>=0.48.0` under
`python_version >= "3.14"`), every binary dependency in the chain (`pydantic-core`, `cryptography`, `pywin32`)
ships `cp314` **and** `cp315` `win_amd64` wheels, and a full resolution succeeds at 29 packages. The
`requires-python >=3.14` pin stays.

**Co-resolution against the real dependency set, checked the same day.** `mcp>=2.3.0` added to this project's
exact dependency list resolves to 81 packages with no conflict, and every version already in `uv.lock` stays put:
`fastapi` 0.162.0, `starlette` 1.10.0, `uvicorn` 0.54.0, `httpx` 0.28.1, `anyio` 4.15.1 are unchanged, and only
`pydantic` moves, by a patch (2.14.1 → 2.14.2, and `uv add` may well keep even that). Adding the SDK is close to
a no-op for the doc plane. `uv` 0.13.6 is now installed.

**Correction to an earlier note in this file:** the SDK brings `httpx2`, but `httpx` is a runtime dependency of
the project already (through `qdrant-client` and `fastembed`), so both are in the tree whatever we choose, and
there is no "two HTTP stacks" cost to avoid. Write the plane clients against **`httpx`**, which the rest of the
project already uses, and declare it explicitly in `[project.dependencies]` instead of leaning on a transitive.

## 10. Open questions

1. ~~**Who bootstraps the code plane?**~~ **Closed 2026-10-30:** out of scope. The code plane team owns
   onboarding; this connector only queries. The practical consequence stands — the code tools return nothing
   useful for a project that was never bootstrapped — so M3 should say so clearly rather than look broken.
2. **Is one spawn always one project?** **Deferred 2026-10-30**, with per-spawn kept as the standing default
   (decision 4): identity from the environment, `project_id` in no tool schema, no way for an agent to express
   another project. The DevX team decides when they settle how a session maps to a project. Reversing it is
   about an hour of code (`render.py` stops hiding the argument, `doc_client.py` stops injecting it); the real
   cost is that every tool signature changes for consumers, and the isolation stops being structural and needs
   replacing with a check that stdio gives no natural place for.
3. ~~**Does DevX need doc-plane sync control as a tool?**~~ **Closed 2026-10-31: no.** The surface stays
   read-only, matching the code plane. The staleness is also narrower than first written here: rules and
   templates are read live from the host (the catalog rebuilds when the branch head moves), so only
   `project-data/` evidence waits for the nightly sync or a *Sync now*. A refresh tool would be the one write
   in a read-only surface, costing host calls and embedding on an agent's say-so. Revisit if DevX asks.
4. ~~**Resources and prompts.**~~ **Closed 2026-10-30:** tools only (decision 10).

~~Also open, for M2: whether a running code plane will be reachable for testing.~~ **Closed 2026-10-31:** it
was. The adapter was run locally against a `file://` repo (`ASTRA_ALLOW_FILE_REPOS=1`), so the code tools and the
envelope are verified against the real implementation, not only the contract. Document retrieval is the part
still unverified end to end, needing a golden repo, a PAT and Qdrant.

## 11. Risks

| Risk | Mitigation |
|---|---|
| ~~MCP SDK not installable on Python 3.14~~ | **Cleared 2026-10-30**, see the M0 note in section 9 |
| Doc plane unreachable at spawn, so no schemas | Fail startup with a clear message; do not serve a half-empty tool list |
| Agent passes an unqualified symbol; `ambiguous` refuses by default | Return alternatives in the content so the agent can retry qualified |
| Code bootstrap is heavy (about 7 minutes, 2 GB for a 3,000-file repo) | Not on the query path; keep it in the onboarding CLI (open question 1) |
| Schema drift if doc tools are ever redeclared here | Decision 5: always fetch, never copy |
