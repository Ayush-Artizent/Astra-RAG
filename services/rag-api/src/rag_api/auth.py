"""AuthN/Z. The tenant is derived from the credential, never from the request body (§9)."""

from __future__ import annotations

import hmac
import json
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rag_api.config import ApiSettings, AuthMode
from rag_api.deps import get_settings
from rag_core.tenancy import TenantContext

_bearer = HTTPBearer(auto_error=False)


def authenticate(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TenantContext:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    match settings.auth_mode:
        case AuthMode.API_KEY:
            keys: dict[str, str] = json.loads(settings.api_keys_json.get_secret_value())
            for key, tenant in keys.items():
                if hmac.compare_digest(key, creds.credentials):
                    return TenantContext(tenant_id=tenant, principal=f"apikey:{key[:6]}…")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
        case AuthMode.ENTRA:
            # TODO(platform pod): validate JWT (issuer, audience, signature via JWKS), map the
            # service principal / app role claim to tenant_id via Postgres tenant config.
            raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Entra auth not wired yet")


Tenant = Annotated[TenantContext, Depends(authenticate)]
