"""Signs the internal envelope the code adapter verifies.

Mirrors `code-adapter/src/envelope.ts`: the wire format is
`base64url(JSON payload).base64url(HMAC-SHA256(that first part, key))`, unpadded.
Org and project come from this server's configuration, never from a caller, which is what the
adapter relies on: it takes the tenant from the envelope alone.
"""
import base64
import hmac
import json
import time
import uuid
from hashlib import sha256

from .config import Config

HEADER = "X-Astra-Envelope"
# The adapter refuses anything over 300 s. A minute is plenty for one call and leaves room for the
# 30 s of clock skew it tolerates.
LIFETIME_SECONDS = 60


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_request_id() -> str:
    return str(uuid.uuid4())


def sign(config: Config, scopes: list[str], request_id: str, now: int | None = None) -> str:
    """The header value for one call. A fresh one per call: they are short-lived by design."""
    issued = int(time.time()) if now is None else now
    payload = {
        "org_id": config.org_id,
        "project_id": config.project_id,
        "scopes": scopes,
        "request_id": request_id,
        "iat": issued,
        "exp": issued + LIFETIME_SECONDS,
    }
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64u(hmac.new(config.envelope_key.encode("utf-8"), body.encode("ascii"), sha256).digest())
    return f"{body}.{signature}"
