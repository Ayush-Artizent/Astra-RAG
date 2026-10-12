"""Webhook receiver (§4.1 step 1): validate signature, enqueue ``{tenant, repo, new_sha}``, return.

Each tenant gets its own webhook URL + secret. The tenant is taken from the URL *only after*
the secret for that tenant verifies, so a caller cannot inject jobs into another tenant.
"""

from __future__ import annotations

import hmac
import json
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from rag_core.schemas import GitHost
from rag_ingest.config import IngestSettings
from rag_ingest.jobs import IngestJob, JobReason
from rag_ingest.queue import InMemoryQueue, JobQueue

app = FastAPI(title="astra-rag-ingest-webhooks", version="0.1.0")


@lru_cache
def get_settings() -> IngestSettings:
    return IngestSettings()


@lru_cache
def get_queue() -> JobQueue:
    # TODO(ingestion pod): ServiceBusQueue when ASTRA_SERVICEBUS_CONNECTION_STRING is set.
    return InMemoryQueue()


def _verify(tenant_id: str, presented: str | None, settings: IngestSettings) -> None:
    secrets: dict[str, str] = json.loads(settings.webhook_secrets_json.get_secret_value())
    expected = secrets.get(tenant_id)
    if not expected or not presented or not hmac.compare_digest(expected, presented):
        # Same response for unknown tenant and bad secret: don't leak which tenants exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook credentials")


Settings = Annotated[IngestSettings, Depends(get_settings)]
Queue = Annotated[JobQueue, Depends(get_queue)]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/{tenant_id}/gitlab", status_code=status.HTTP_202_ACCEPTED)
async def gitlab_push(
    tenant_id: str,
    request: Request,
    settings: Settings,
    queue: Queue,
    x_gitlab_token: Annotated[str | None, Header()] = None,
    x_gitlab_event: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _verify(tenant_id, x_gitlab_token, settings)
    if x_gitlab_event != "Push Hook":
        return {"queued": False, "reason": "ignored event"}
    body = await request.json()
    project = body.get("project", {})
    default_branch = project.get("default_branch", "main")
    if body.get("ref") != f"refs/heads/{default_branch}":
        return {"queued": False, "reason": "not default branch"}
    job = IngestJob(
        tenant_id=tenant_id,
        repo=project["path_with_namespace"],
        host=GitHost.GITLAB,
        new_sha=body["after"],
        reason=JobReason.WEBHOOK,
    )
    await queue.enqueue(job, delay_seconds=settings.debounce_seconds)
    return {"queued": True, "job_id": job.job_id}


@app.post("/webhooks/{tenant_id}/azure-repos", status_code=status.HTTP_202_ACCEPTED)
async def azure_repos_push(
    tenant_id: str,
    request: Request,
    settings: Settings,
    queue: Queue,
    x_astra_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    # Azure DevOps service hooks support custom headers; configure X-Astra-Webhook-Secret there.
    _verify(tenant_id, x_astra_webhook_secret, settings)
    body = await request.json()
    if body.get("eventType") != "git.push":
        return {"queued": False, "reason": "ignored event"}
    resource = body["resource"]
    repo = resource["repository"]
    default_ref = repo.get("defaultBranch", "refs/heads/main")
    updates = [u for u in resource.get("refUpdates", []) if u.get("name") == default_ref]
    if not updates:
        return {"queued": False, "reason": "not default branch"}
    job = IngestJob(
        tenant_id=tenant_id,
        repo=f"{repo['project']['name']}/{repo['name']}",
        host=GitHost.AZURE_REPOS,
        new_sha=updates[-1]["newObjectId"],
        reason=JobReason.WEBHOOK,
    )
    await queue.enqueue(job, delay_seconds=settings.debounce_seconds)
    return {"queued": True, "job_id": job.job_id}
