# Astra RAG

Enterprise RAG-as-a-Service for the Agentic SDLC platform: production-grade **context retrieval**
over customer code repos and golden docs, so agents can turn Jira/ADO tickets into BRDs.
This service only retrieves context. It does not generate BRDs.

- **Design doc:** *Enterprise RAG as a Service: Design Document (Draft v1)*,
  <https://claude.ai/artifact/PfEuBDHNf9E8tCuouwZr51>. Section numbers (§) in code refer to it.
- **Design → code map:** [docs/architecture.md](docs/architecture.md)
- **Open decisions and assumptions:** [docs/decisions.md](docs/decisions.md)

## Repo layout

```text
packages/
  rag-core/       schemas, tenancy enforcement, provenance, redaction, swappable interfaces, memory backends
  rag-parsers/    parser plugin interface, registry, window + markdown chunkers (tree-sitter: TODO)
services/
  rag-ingest/     webhook receiver, incremental index pipeline, worker, reconciler
  rag-api/        FastAPI core API: agent tools, retrieval pipeline (hybrid, RRF, rerank, pack, cite)
  rag-mcp/        MCP server, a thin wrapper over rag-api via the SDK
  rag-eval/       offline eval harness, metrics, CI regression gate
sdk/
  python/         astra-rag-sdk (async client, same tool shapes as REST/MCP)
  typescript/     generated from OpenAPI (planned)
db/migrations/    Postgres schema with row-level security per tenant
deploy/           Dockerfile (one image per service) + AKS/KEDA manifests
eval/             datasets (smoke set committed; real tenant data never committed) + baselines
docs/             architecture map, decisions log, ADRs
```

It is a single [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with one
lockfile, and every package is installed editable into one venv.

## Quick start

Prereqs: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Docker (optional, for Postgres, Azurite and Jaeger).

```bash
uv sync                      # create .venv and install every workspace package + dev tools
cp .env.example .env
uv run poe check             # ruff + mypy --strict + pytest
uv run poe api               # rag-api on :8080 with in-memory backends + a demo corpus
```

Try it:

```bash
curl -s localhost:8080/v1/tools/search_code \
  -H "Authorization: Bearer dev-key-tenant-a" -H "content-type: application/json" \
  -d '{"query": "refund eligibility", "k": 3, "caller": {"ticket_id": "PAY-1"}}'
```

Every response carries `results[]` with SHA-pinned citations, plus `trace_id`, `snapshot`
(repo → indexed_sha), `index_version` and per-stage `timing`. Open <http://localhost:8080/docs> for the OpenAPI UI.

Run `uv run poe --help` to see all tasks:

| Task | What it does |
|---|---|
| `poe check` | lint + typecheck + all tests (same as CI) |
| `poe test-tenancy` | cross-tenant leak tests only |
| `poe api` / `poe ingest-webhook` / `poe mcp` | run a service locally |
| `poe eval` | run `eval/datasets/smoke.jsonl` against a running API |
| `poe openapi` | export the OpenAPI spec (source for the TS SDK) |

Local infra: `docker compose up -d` starts Postgres (pgvector, migrations auto-applied), Azurite
(Blob), and Jaeger (traces, at <http://localhost:16686>). Azure AI Search and Service Bus have no
good local emulators, so local runs use the in-memory backends from `rag_core.memory`.

## Non-negotiables

These come from design doc §2. CI and code review enforce them.

1. **Tenant isolation.** No function in the data-access layer accepts `tenant_id` from a
   caller. Stores read it from `rag_core.tenancy`, which is bound once per request (from the
   credential) or per job (from the queue envelope). Leak tests (`-m tenancy`) are a required CI check.
   Postgres adds row-level security on top.
2. **Redact before anything else.** Secrets and PII are removed before chunking, embedding and
   logging. If redaction fails, the file is not indexed. Query text is redacted before it is traced.
3. **Provenance is a field, not a feature.** Every chunk and result carries the commit SHA, line
   range and content hash. Citations deep-link to the SHA.
4. **Incremental by default.** Ingestion diffs by commit and skips unchanged content by hash.
5. **Everything swappable.** The chunk store, graph store, embedder, reranker, LLM, git host and
   blob store all sit behind the `Protocol`s in `rag_core.interfaces`.
6. **Measure first.** Changes to chunking, embeddings, ranking or prompts ship with an eval
   report and must pass the eval gate. Bump `INDEX_VERSION` when stored shape or semantics change.

## Status

This is the project template. The skeleton runs and is tested end-to-end with in-memory backends.
The `TODO(<pod>)` markers in the code are Phase 1 work: Azure backends, git host clients,
tree-sitter chunkers, Entra auth and Service Bus. See the backlog in
[docs/architecture.md](docs/architecture.md#phase-1-backlog-by-pod).
