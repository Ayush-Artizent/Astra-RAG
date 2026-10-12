from __future__ import annotations

from enum import StrEnum

from pydantic import SecretStr

from rag_core.config import CoreSettings


class AuthMode(StrEnum):
    API_KEY = "api_key"  # local/dev only
    ENTRA = "entra"  # Entra ID / service principals; tenant from token claims (§9)


class ApiSettings(CoreSettings):
    auth_mode: AuthMode = AuthMode.API_KEY
    # LOCAL ONLY: JSON {"<api-key>": "<tenant_id>"}. Never used when auth_mode=entra.
    api_keys_json: SecretStr = SecretStr(
        '{"dev-key-tenant-a": "t_dev_a", "dev-key-tenant-b": "t_dev_b"}'
    )
    entra_audience: str | None = None
    entra_issuer: str | None = None

    rrf_k: int = 60
    candidate_k: int = 100  # per retriever, before fusion/rerank (§7.1)
    default_token_budget: int = 8000
    # Load a tiny demo corpus into the memory stores at startup (local env only).
    seed_demo_data: bool = True
