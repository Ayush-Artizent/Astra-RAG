from __future__ import annotations

from pydantic import SecretStr

from rag_core.config import CoreSettings


class IngestSettings(CoreSettings):
    # Coalesce events for the same repo within this window into one job (§4.1 step 2)
    debounce_seconds: int = 180
    # Hard per-file size cap; larger files are skipped as likely generated/binary (§4.1 step 4)
    max_file_bytes: int = 1_000_000
    # LOCAL ONLY: JSON map {"tenant_id": "webhook-secret"}. In Azure, secrets come from Key Vault.
    webhook_secrets_json: SecretStr = SecretStr("{}")
    embed_batch_size: int = 64
