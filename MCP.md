# ASTRA MCP server

A **connector**. It exposes two services that already exist — this app (the **document plane**) and the
CodeGraph adapter (the **code plane**) — to an MCP client such as DevX, over stdio. It holds no database, no
lock and no models: every answer comes from a plane. It routes, renames and explains; it does not retrieve.

The planes are built and run by their own teams. Nothing here changes either of them.

## What it serves

| Tool | Plane | For |
|---|---|---|
| `get_document_context` | document | The rules that apply, the whole template, and evidence from the project's data |
| `search_project_data` | document | A targeted search when a section lacks evidence |
| `find_symbol` | code | Where symbols are defined, by qualified name or keyword |
| `find_callers` | code | What calls a symbol, and from where |
| `analyze_impact` | code | What depends on a symbol, so what a change could break |
| `trace_flow` | code | The path through the code between two or more symbols |
| `code_index_status` | code | Whether the code index is ready, and how fresh |

The document tools are **fetched** from the plane at every listing, not declared here, so a tool that team adds
appears by itself, with the project's live `doc_type` enum. The code tools are **built from** the vendored
contract (see *Keeping the contract current*).

## Before it will work

1. The document plane is running (`uv run python -m astra_rag`) with Qdrant up, and the project is bound to a
   golden repo (`PUT /api/projects/{id}/binding`).
2. The code adapter is running, and the project has been bootstrapped on it. **Onboarding a repo to the code
   plane is that team's job**; this server only queries. Until it is done, code tools answer `not_ready` and say so.
3. Both this server and the adapter share one `ASTRA_ENVELOPE_KEY`.
4. The project id works on **both** planes: `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. No dots, and it must start with
   a letter or digit. Startup refuses anything else, which is deliberate — see *Troubleshooting*.

## Spawning it

An MCP client needs a command and an environment. Running from this checkout:

```json
{
  "command": "uv",
  "args": ["run", "--directory", "C:\Projects\Orchestrator", "astra-mcp"],
  "env": {
    "ASTRA_ORG_ID": "nous",
    "ASTRA_PROJECT_ID": "devx-123",
    "ASTRA_ENVELOPE_KEY": "<the same secret the code adapter has>"
  }
}
```

| Variable | Required | Default |
|---|---|---|
| `ASTRA_ORG_ID` | yes | — |
| `ASTRA_PROJECT_ID` | yes | — |
| `ASTRA_ENVELOPE_KEY` | yes | — (at least 16 characters) |
| `ASTRA_DOC_URL` | no | `http://127.0.0.1:5000` |
| `ASTRA_CODE_URL` | no | `http://127.0.0.1:8091` |
| `ASTRA_MCP_TIMEOUT_MS` | no | `30000` |

**One process, one project.** Identity is read once at spawn, and `project_id` appears in no tool schema, so a
client cannot ask about another project — it has no way to say it. Several projects means several processes,
which is how MCP clients spawn servers anyway. If that ever has to change, it changes every tool's signature.

## Reading what comes back

Three different things, deliberately kept apart:

- **A note**, a plain line in a content block *before* the payload. The answer arrived but is partial: an index
  that is not ready, a sync in progress, an ambiguous symbol that was refused, content cut by the token budget.
  The payload after it is exactly what the plane sent. A healthy answer has no note.
- **An error result** (`isError`). The plane refused the call and said why — a bad argument, an unknown tool.
  The model can read it and try again.
- **A protocol error.** Only when listing tools fails completely. If one plane is down the other still lists.

Everything a tool returns is **reference data, not instructions**; both the server's own instructions and the
document plane's notice say so. Treat repository content as data when you pass it to a model.

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| Exits 2 before starting | A setting is missing or malformed | The message names the variable |
| `could not be reached (ConnectError)` | That plane is not running, or the URL is wrong | Start it; check `ASTRA_DOC_URL` / `ASTRA_CODE_URL` |
| Only code tools are listed | The document plane is down | Check the server's stderr, which says so |
| **401 from the code plane** | The key differs from the adapter's — **or the project id has a dot or a leading `_`/`-`** | Compare keys first; then the id. A bad id reads as an auth failure, which is why startup checks it |
| Code tools say `not_ready` | The project was never bootstrapped there | The code plane team onboards it |
| A symbol "matched several symbols" | The adapter refuses ambiguous names rather than guessing | Ask again with a qualified name, or `path/to/file.py::Name` |
| No rules in a document answer | The golden repo has no `golden.yaml`, so nothing is scoped | That repo's owners add one |

## Trying it without a golden repo

The code half can be exercised on its own, with no host, PAT or Qdrant. The adapter accepts a local repository
when it is started with `ASTRA_ALLOW_FILE_REPOS=1` (its own config calls this development-only), so a small git
repo is enough to get a real index:

1. Start the adapter with `ASTRA_ENVELOPE_KEY`, `ASTRA_ALLOW_FILE_REPOS=1` and an `ASTRA_DATA_DIR`.
2. Bootstrap it: `POST /internal/v1/code/jobs` with `{"type": "bootstrap", "repo_url": "file:///path/to/repo"}`
   and an envelope signed with scope `project:admin`. This server only ever signs `query`, so that call needs a
   script of its own — it is the bootstrap step the code plane team owns.
3. Poll `/internal/v1/code/jobs/{id}` until `done`, then spawn `astra-mcp` and use the code tools.

Done this way on 2026-10-31 with a three-file TypeScript repo: the index came back `ready` with 8 symbols, and
`find_callers` returned the real callers. The document tools will answer `This project is not bound to a
repository.` until a golden repo is bound, which is the correct refusal, not a fault in this server.

**Stopping the adapter:** `npm start` spawns a child process that outlives it, so killing the npm process leaves
the server listening. Kill whatever holds the port.

## Keeping the contract current

`src/astra_mcp/contracts/code-adapter.openapi.yaml` is a copy of the code plane's contract, and the code tools
are built from it at import, so their arguments and limits cannot drift from the adapter silently.

When the code plane changes its contract: replace that file, update the commit in `contracts/SOURCE.md`, and run
the tests. `tests/mcp/test_code_contract.py` fails naming what no longer matches. Only the contract is copied,
never the adapter itself — it is a separate service, and vendoring a moving codebase would rot.

## Testing

```bash
uv run python -m unittest discover -s tests -t .
```

`tests/mcp/` covers it: the planes are faked through `httpx.MockTransport`, so nothing needs the network or a
real token. `test_stdio.py` is the exception and the most valuable one — it spawns the real server, speaks real
MCP over its stdin and stdout, and serves both planes from loopback sockets, so it exercises the path a client
actually takes rather than a mocked one.
