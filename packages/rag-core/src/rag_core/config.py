"""Shared settings. Every service extends :class:`CoreSettings`; values come from env / .env.

Secrets (DB passwords, API keys, git tokens) are *never* committed: in Azure they come from
Key Vault via workload identity; locally from ``.env`` (see ``.env.example``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASTRA_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Environment = Environment.LOCAL
    log_level: str = "INFO"
    log_json: bool = False

    # State / metadata / graph (§12)
    postgres_dsn: SecretStr = SecretStr("postgresql://astra:astra@localhost:5432/astra")

    # Blob: immutable chunk snapshots + audit (§8)
    blob_connection_string: SecretStr | None = None
    blob_snapshot_container: str = "snapshots"

    # Queue (§12): Azure Service Bus
    servicebus_connection_string: SecretStr | None = None
    ingest_queue: str = "ingest-jobs"
    backfill_queue: str = "backfill-jobs"

    # Pluggable backends (§2 principle 6). Names resolve via rag_core.registry.
    chunk_store: str = Field(default="memory", description="memory | azure_ai_search | pgvector")
    graph_store: str = Field(default="memory", description="memory | postgres")
    embedder: str = Field(default="fake", description="fake | azure_openai")
    reranker: str = Field(
        default="passthrough", description="passthrough | azure_semantic | cross_encoder"
    )

    # Azure OpenAI (model policy is still [DECISION], see docs/decisions.md)
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_embedding_deployment: str | None = None

    # Azure AI Search
    azure_search_endpoint: str | None = None
    azure_search_api_key: SecretStr | None = None
