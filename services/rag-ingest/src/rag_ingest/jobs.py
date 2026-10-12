from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from rag_core.schemas import GitHost


class JobReason(StrEnum):
    WEBHOOK = "webhook"
    RECONCILE = "reconcile"
    BACKFILL = "backfill"


class IngestJob(BaseModel):
    """Queue envelope ``{tenant, repo, new_sha}`` (§4.1 step 1). Workers bind tenant from this."""

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    tenant_id: str
    repo: str
    host: GitHost
    new_sha: str
    reason: JobReason = JobReason.WEBHOOK

    @property
    def coalesce_key(self) -> str:
        """Service Bus session id: one in-flight job per repo; later SHAs supersede earlier ones."""
        return f"{self.tenant_id}:{self.repo}"
