"""Decoding a host's JSON reply, shared by adapters."""
import json
from collections.abc import Callable

from ..errors import AppError


def parse_json(body: bytes, host_label: str, unauthorized: Callable[[], AppError] | None = None):
    """Parse `body`; an HTML page means the host sent a sign-in page, which `unauthorized` (if given) turns into an error."""
    if unauthorized and body.lstrip()[:1] == b"<":
        raise unauthorized()
    try:
        return json.loads(body)
    except ValueError:
        raise AppError(f"{host_label} returned a response that could not be read.", 502) from None
