-- Astra RAG: initial Postgres schema (design doc §4, §6.3, §8, §9, §12).
-- Index state, tenant config, dependency graph, ingest runs, traces and feedback.
--
-- Tenant isolation is enforced twice:
--   1. App layer: rag_core.tenancy (stores read the tenant from context, never from callers).
--   2. DB layer: row-level security keyed on the session setting `astra.tenant_id`, which the
--      data-access layer sets per transaction:  SET LOCAL astra.tenant_id = '<tenant>';
-- The app connects as `astra_app` (RLS enforced). Migrations run as the owner.
--
-- Migration tooling (Alembic vs. plain SQL runner) is still open; see docs/decisions.md.
-- Phase 2/3 tables are created now because schemas are cheap and migrations later are not (§14).

CREATE EXTENSION IF NOT EXISTS vector;   -- kept available for the pgvector ChunkStore alternative

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'astra_app') THEN
    CREATE ROLE astra_app LOGIN PASSWORD 'astra_app';  -- local only; Entra auth in Azure
  END IF;
END $$;

-- ---------------------------------------------------------------- tenants
CREATE TABLE tenants (
  tenant_id      text PRIMARY KEY,
  display_name   text NOT NULL,
  index_layout   text NOT NULL DEFAULT 'shared' CHECK (index_layout IN ('shared', 'dedicated')),
  model_policy   jsonb NOT NULL DEFAULT '{"provider": "azure_openai"}',   -- §12 per-tenant policy
  filter_rules   jsonb NOT NULL DEFAULT '{}',   -- per-tenant include/exclude overrides (§4.1)
  redaction_cfg  jsonb NOT NULL DEFAULT '{}',   -- allowlists etc. (§9)
  created_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- repos / index state
CREATE TABLE repos (
  tenant_id         text NOT NULL REFERENCES tenants(tenant_id),
  repo              text NOT NULL,
  host              text NOT NULL CHECK (host IN ('azure_repos', 'gitlab')),
  web_url           text,
  default_branch    text NOT NULL DEFAULT 'main',
  trust_tier        text NOT NULL DEFAULT 'standard' CHECK (trust_tier IN ('golden', 'standard')),
  last_indexed_sha  text,
  indexed_at        timestamptz,
  summary           text,                 -- Phase 2: repo summary for routing (§6.2)
  enabled           boolean NOT NULL DEFAULT true,
  PRIMARY KEY (tenant_id, repo)
);

-- ---------------------------------------------------------------- ingest runs (observability)
CREATE TABLE ingest_runs (
  job_id         text PRIMARY KEY,
  tenant_id      text NOT NULL REFERENCES tenants(tenant_id),
  repo           text NOT NULL,
  reason         text NOT NULL,           -- webhook | reconcile | backfill
  old_sha        text,
  new_sha        text NOT NULL,
  status         text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'superseded')),
  report         jsonb,                   -- IngestReport: counts only, never content or secrets
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz
);
CREATE INDEX ingest_runs_repo_idx ON ingest_runs (tenant_id, repo, started_at DESC);

-- ---------------------------------------------------------------- dependency graph (§6.3)
CREATE TABLE graph_nodes (
  tenant_id   text NOT NULL REFERENCES tenants(tenant_id),
  node_id     text NOT NULL,              -- e.g. repo:payments, file:payments/src/a.py, api:GET /refunds
  kind        text NOT NULL CHECK (kind IN ('repo','module','file','symbol','api','table','doc')),
  repo        text,
  path        text,
  attrs       jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (tenant_id, node_id)
);

CREATE TABLE graph_edges (
  tenant_id   text NOT NULL REFERENCES tenants(tenant_id),
  src         text NOT NULL,
  dst         text NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('imports','calls','depends_on','exposes_api',
                                            'consumes_api','reads_table','writes_table','documents')),
  confidence  real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  source      text NOT NULL CHECK (source IN ('manifest','parser','heuristic')),
  repo        text NOT NULL,              -- repo that produced the edge (for incremental deletes)
  src_path    text,
  commit_sha  text NOT NULL,
  PRIMARY KEY (tenant_id, src, dst, kind)
);
CREATE INDEX graph_edges_dst_idx ON graph_edges (tenant_id, dst);   -- reverse walk = impact
CREATE INDEX graph_edges_repo_path_idx ON graph_edges (tenant_id, repo, src_path);

-- ---------------------------------------------------------------- retrieval traces (§8 tier 2)
-- MVP keeps basic fields; Phase 3 moves audit copies to WORM Blob with hash chaining.
CREATE TABLE retrieval_traces (
  trace_id        text PRIMARY KEY,
  tenant_id       text NOT NULL REFERENCES tenants(tenant_id),
  tool            text NOT NULL,
  caller          jsonb NOT NULL,         -- platform, agent_run_id, ticket_id
  query_redacted  text NOT NULL,          -- ALWAYS redacted before insert
  query_rewritten jsonb NOT NULL DEFAULT '[]',
  filters         jsonb NOT NULL DEFAULT '{}',
  candidates      jsonb NOT NULL DEFAULT '{}',
  selected        jsonb NOT NULL DEFAULT '[]',
  snapshot        jsonb NOT NULL DEFAULT '{}',
  models          jsonb NOT NULL DEFAULT '{}',
  index_version   integer NOT NULL,
  latency_ms      real NOT NULL,
  prev_hash       text,                   -- Phase 3: hash chain for tamper evidence
  record_hash     text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX retrieval_traces_tenant_time_idx ON retrieval_traces (tenant_id, created_at DESC);

CREATE TABLE feedback (
  id          bigserial PRIMARY KEY,
  tenant_id   text NOT NULL REFERENCES tenants(tenant_id),
  trace_id    text NOT NULL REFERENCES retrieval_traces(trace_id),
  chunk_id    text,
  label       text NOT NULL CHECK (label IN ('relevant','irrelevant','missing')),
  comment     text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- row-level security
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['tenants','repos','ingest_runs','graph_nodes','graph_edges',
                           'retrieval_traces','feedback'] LOOP
    -- Not FORCEd: the owner role (migrations, and the reconciler's tenant enumeration) bypasses
    -- RLS. Every request/job path must connect as astra_app.
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''astra.tenant_id'', true)) '
      'WITH CHECK (tenant_id = current_setting(''astra.tenant_id'', true))', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO astra_app', t);
  END LOOP;
END $$;
GRANT USAGE ON SEQUENCE feedback_id_seq TO astra_app;
