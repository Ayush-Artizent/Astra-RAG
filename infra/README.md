# Infrastructure (Azure)

The IaC tool is still open: Bicep vs. Terraform, decision D7 in [docs/decisions.md](../docs/decisions.md).
Once it is chosen, it goes in this folder with one environment per directory (`dev`, `staging`, `prod`).

## Resources the MVP needs

These are the defaults from design doc §12.

| Resource | Purpose | Notes |
|---|---|---|
| AKS + KEDA + Workload Identity | runs every service | Secrets Store CSI driver for Key Vault |
| Azure Container Registry | images | CI pushes via an OIDC federated credential |
| Azure Service Bus (Standard or Premium) | `ingest-jobs` and `backfill-jobs` queues | **sessions enabled** for per-repo coalescing; DLQ |
| Azure AI Search | hybrid chunk index | Check index-count and storage limits per tier **before** deciding D3 |
| Azure Database for PostgreSQL Flexible Server | state, graph, traces, tenant config | apply `db/migrations`; the app connects as `astra_app` (RLS) |
| Storage account (Blob) | content-addressed chunk snapshots; Phase 3 WORM audit | immutability policies on the audit container |
| Azure OpenAI | embeddings (+ LLM per model policy) | **request TPM quota early**, since backfill is quota-bound (§11, §14) |
| Key Vault | git tokens, webhook secrets, keys | per-tenant CMK where required (§9) |
| Azure Monitor / App Insights | OTel traces, metrics, logs | per-tenant cost dashboards (§11) |
