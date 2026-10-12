# Decisions, assumptions and open questions

This is the living tracker for the design doc's **[DECISION]** and **[ASSUMPTION]** markers.
When a decision is made, record it in an ADR under `docs/adr/` and link the ADR here.

## Open decisions

| # | Decision | Default in code today | Swap point | Owner | Status |
|---|---|---|---|---|---|
| D1 | Chunk store: Azure AI Search vs. Postgres/pgvector + OpenSearch (§6.1) | memory; Azure AI Search planned | `ChunkStore`, `ASTRA_CHUNK_STORE` | Index & retrieval | Open |
| D2 | Graph DB: Postgres recursive queries vs. a dedicated graph DB (§6.3) | Postgres tables in `0001_init.sql` | `GraphStore`, `ASTRA_GRAPH_STORE` | Index & retrieval | Default: Postgres; revisit only if traversal performance demands it |
| D3 | Index layout: shared index with tenant filter vs. dedicated index per large tenant (§9). Check AI Search tier limits first | `tenants.index_layout` column | `ChunkStore` impl | Platform | Open |
| D4 | Embedding model (§12) | `FakeEmbedder`; Azure OpenAI planned | `Embedder`, `ASTRA_EMBEDDER` | Index & retrieval | Benchmark on our own code and docs with rag-eval before locking in |
| D5 | Reranker: Azure semantic ranker vs. hosted cross-encoder (§12) | passthrough | `Reranker`, `ASTRA_RERANKER` | Index & retrieval | Benchmark both |
| D6 | LLM for query rewrite and summaries, plus the **model policy** (which models may see customer code) (§12) | none called yet | `ModelProvider`, `tenants.model_policy` | Platform + legal/security | **Blocks pilot onboarding.** Needs legal/security sign-off |
| D7 | IaC tool: Bicep vs. Terraform | none | `infra/` | Platform | Open |
| D8 | DB migration tooling: Alembic vs. a plain SQL runner | plain SQL in `db/migrations/` | - | Platform | Open |
| D9 | Top N languages that get tree-sitter chunkers in Phase 1 | window fallback for all languages | `rag_parsers` registry | Index & retrieval | Decide in week 1 from pilot tenants |

## Assumptions to confirm

These came from the design interview and should be confirmed.

| # | Assumption | Where it shows up in code |
|---|---|---|
| A1 | Tenant-level isolation only; no per-user ACLs | `TenantContext` has no user scope |
| A2 | Default branch only | webhook handlers ignore non-default refs |
| A3 | Freshness SLO is p95 ≤ 60 min from push to searchable | `debounce_seconds=180`, nightly reconciler |
| A4 | Largest tenant has 10M–100M LOC across hundreds of repos | backfill queue, content-hash dedupe |
| A5 | Jira/ADO tickets are query sources, not indexed sources | no ticket connector |
| A6 | Azure Repos and GitLab are the only MVP git hosts | `GitHost` enum |

## Template choices made by the platform engineer

These are cheap to change. Raise a PR if you disagree.

- **Monorepo with a uv workspace.** One lockfile, editable installs, and one CI (ADR-0001).
- **Python 3.12 or newer.** CI tests 3.12 and 3.13; images use 3.12.
- **Ruff, strict mypy and pytest.** `poe` is the task runner because it works on Windows without `make`.
- **Shared request models live in `rag-core`.** REST, MCP and the SDK cannot drift apart.
- **The MCP server calls rag-api through the SDK.** It contains no retrieval logic of its own.
- **Tenancy is enforced twice.** Once in the app (context-bound stores) and once in the DB (Postgres RLS).
- **Phase 2/3 columns already exist.** Trace hash chain, repo summaries and tenant model policy
  are in the schema now, because schemas are cheap and migrations later are not.
- **GitHub Actions for CI**, because the repo is on GitHub. Switch to Azure Pipelines if the
  org standard requires it.

## Open questions

The design doc's §15 is empty, so here are a first set to discuss:

1. What is the BRD generator's contract for claim-level citations (`statement → chunk_id[]`)? This is Phase 3, but agreeing on the shape early is cheap.
2. Who are the 2–3 pilot tenants? Which languages do they use, how big are they, and which git hosts?
3. Is Azure OpenAI quota (TPM) for backfill already requested? It is the likely bottleneck (§11).
4. Who owns SME labeling time, and when does it start?
5. What retention policy applies to traces and snapshots per tenant?
