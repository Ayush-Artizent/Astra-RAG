# Kubernetes manifests (AKS)

Plain Kustomize base for the deployable units in design doc §3. Overlays per environment
(`dev`, `staging`, `prod`) are added once the Azure landing zone exists (see `infra/`).

| Manifest | Unit | Scaling |
|---|---|---|
| `rag-api.yaml` | `rag-api` (FastAPI) | HPA on CPU; target p95 < 1–2 s for search tools |
| `rag-ingest-webhook.yaml` | webhook receiver | 2 replicas; stateless, returns immediately |
| `rag-ingest-worker.yaml` | ingest workers | **KEDA** on Service Bus queue depth (incl. scale-to-zero for backfill) |
| `rag-reconciler.yaml` | nightly reconciler | CronJob (§4.2, mandatory: webhooks get lost) |

Secrets are never in these files. Pods use **Azure Workload Identity** and read from Key Vault
via the Secrets Store CSI driver (`SecretProviderClass` per environment overlay).

```bash
kubectl kustomize deploy/k8s            # render
kubectl apply -k deploy/k8s             # apply (dev cluster)
```
