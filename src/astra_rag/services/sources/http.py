"""Shared GET helpers for host REST APIs, so every adapter maps failures the same way."""
import json
import urllib.error
import urllib.request

from ...config import HTTP_TIMEOUT_SECONDS
from ..errors import AppError
from .errors import map_http_error, unreachable


def get_bytes(url: str, headers: dict[str, str], host_label: str, not_found: str | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise map_http_error(exc, host_label, not_found) from None
    except (urllib.error.URLError, TimeoutError):
        raise unreachable(host_label) from None


def get_json(url: str, headers: dict[str, str], host_label: str, not_found: str | None = None):
    body = get_bytes(url, headers, host_label, not_found)
    try:
        return json.loads(body)
    except ValueError:
        raise AppError(f"{host_label} returned a response that could not be read.", 502) from None
