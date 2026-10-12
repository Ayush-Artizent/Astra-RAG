# Architecture: design doc → code

Where each part of the design doc lives in this repo, and what is still a stub.
✅ means implemented and tested. 🟡 means the interface and skeleton exist and the implementation
is Phase 1 work. ⏳ means the work is scheduled for a later phase.

## Data flow

```text
 Azure Repos / GitLab ──push webhook──▶ rag-ingest.webhook ──▶ queue (Service Bus, session per repo)
                                                                   │
                       reconciler (nightly CronJob) ───────────────┤
                                                                   ▼
                                                     rag-ingest.worker → IndexPipeline
   diff → filter → REDACT → parse/chunk → hash → reuse-or-embed → snapshot(Blob) → index + graph → commit pointer
                                                                   │
                                     ┌─────────────────────────────┼─────────────────────────┐
                                     ▼                             ▼                         ▼
                              ChunkStore (AI Search)      GraphStore (Postgres)       BlobStore (snapshots)
                                     ▲                             ▲
   agents ─▶ MCP / SDK / REST ─▶ rag-api: understand → lexical ∥ vector → RRF → rerank → dedupe → pack → cite → trace
```

## Section map

| § | Topic | Code | State |
|---|---|---|---|
| 3 | Deployable units | `services/*`, `deploy/docker/Dockerfile`, `deploy/k8s/` | ✅ skeleton |
| 4.1 | Webhook → enqueue | `rag_ingest/webhook.py` (GitLab + Azure Repos, per-tenant secret) | ✅ |
| 4.1 | Debounce / coalesce | `IngestJob.coalesce_key`, `InMemoryQueue` | 🟡 Service Bus sessions + scheduled msgs |
| 4.1 | Diff / filter / redact / chunk / hash-skip / embed / commit | `rag_ingest/pipeline.py`, `stages/filter.py`, `rag_core/redaction.py` | ✅ with memory backends |
| 4.2 | Reconciler, force-push fallback | `rag_ingest/reconciler.py`, `pipeline.py` (`is_ancestor`) | ✅ logic, 🟡 wiring |
| 4.2 | Backfill queue | `IngestSettings.backfill_queue`, `JobReason.BACKFILL` | 🟡 |
| 4.3 | Version consistency | `Chunk.commit_sha`, `ToolResponse.snapshot` | ✅ |
| 5 | Chunk schema + contextual header | `rag_core/schemas.py` (`Chunk`, `contextual_header`) | ✅ |
| 5 | Parser plugins | `rag_parsers/base.py`, `registry.py` | ✅ |
| 5 | Fallback + Markdown chunkers | `chunkers/window.py`, `chunkers/markdown.py` | ✅ |
| 5 | tree-sitter chunkers | `chunkers/treesitter.py` | 🟡 |
| 6.1 | Hybrid index + identifier-aware analyzer | `ChunkStore` protocol, `rag_core/text.py` (reference tokenizer) | ✅ memory, 🟡 Azure AI Search |
| 6.2 | Hierarchical summaries / routing | `repos.summary` column, `explain_repo` | ⏳ Phase 2 |
| 6.3 | Dependency graph | `GraphStore`, `db/migrations` `graph_*` tables, `find_impacted` | ✅ memory, 🟡 Postgres + manifest parsers |
| 6.4 | Docs/BRD ranking profile | `SIMILAR_REQ_PROFILE`, `DOCS_PROFILE` | ✅ (untuned) |
| 7.1 | Retrieval pipeline | `rag_api/retrieval/service.py`, `fusion.py` | ✅ (glossary expansion and context expansion are Phase 2) |
| 7.2 | Agent tools | `rag_api/routers/tools.py`, `rag_core/api_models.py`, `rag_mcp/server.py`, `sdk/python` | ✅ search/similar/impacted/list/feedback; 🟡 get_file/get_symbol/expand_context |
| 8 T1 | Citations | `rag_core/provenance.py` | ✅ |
| 8 T2 | Retrieval trace | `rag_api/trace.py`, `retrieval_traces` table | ✅ log sink, 🟡 Postgres sink |
| 8 T3 | WORM, hash-chained audit | `retrieval_traces.prev_hash/record_hash` | ⏳ Phase 3 |
| 9 | Tenant isolation | `rag_core/tenancy.py`, RLS in `db/migrations/0001_init.sql`, `-m tenancy` tests | ✅ |
| 9 | AuthN | `rag_api/auth.py` (dev API keys) | 🟡 Entra ID |
| 9 | Redaction | `rag_core/redaction.py` (secrets, regex) | ✅ secrets, 🟡 entropy + PII |
| 10 | Eval | `services/rag-eval`, `eval/datasets`, `eval/baselines`, CI `eval-smoke` | ✅ harness + gate, 🟡 real datasets |
| 11 | Scale | `FileFilter` defaults, cross-repo vector reuse by content hash | ✅ partial |
| 12 | Observability | `rag_core/observability.py`, Jaeger in compose | 🟡 Azure Monitor exporter |

## Key contracts

- **`rag_core.schemas`**: `Chunk`, `Citation`, `ToolResponse`, `TraceRecord`, `Edge`,
  `RepoState`. Any change here is cross-pod and needs platform review (CODEOWNERS).
- **`rag_core.api_models`**: request bodies shared by REST, MCP and the SDK. None of them has a `tenant_id`
  field, and `extra="forbid"` rejects any attempt to send one.
- **`rag_core.interfaces`**: the swappable backends. Implementations read the tenant from
  context. They never take it as a parameter.

## Phase 1 backlog by pod

These are the `TODO(<pod>)` markers in the code.

**Ingestion pod**
- `GitHostClient` implementations: Azure Repos (REST + bare-repo fetch) and GitLab
- Service Bus `JobQueue` (sessions keyed by `coalesce_key`, DLQ, scheduled debounce)
- `worker.build_pipeline` / `reconciler.main` wiring; Postgres `StateStore`; Blob `BlobStore`
- Redaction: entropy detector, Presidio PII tuned on real repos, per-tenant allowlists, redaction report
- Manifest dependency edges (pom, package.json, csproj, requirements, go.mod)

**Index & retrieval pod**
- `AzureSearchChunkStore` with a custom analyzer matching `rag_core.text.tokenize_identifiers`
- `AzureOpenAIEmbedder`; reranker (Azure semantic ranker vs. cross-encoder, benchmarked)
- tree-sitter chunkers for the top customer languages (choose them in week 1)
- `get_file` / `get_symbol` / `expand_context`

**Platform pod**
- Entra ID auth (JWT validation, service principal → tenant mapping)
- Postgres `GraphStore` / `TraceSink` with `SET LOCAL astra.tenant_id` per transaction
- Azure Monitor OTel exporter; IaC (`infra/`); ACR push and CD; TS SDK generation

**Eval**
- Week-1 baseline capture of the current system on real tickets
- Golden-repo dataset (past BRDs → linked code), synthetic queries, SME labeling plan (200–300 tickets)
