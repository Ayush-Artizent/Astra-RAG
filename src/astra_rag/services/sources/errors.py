"""Turns host HTTP failures into AppErrors that are safe to show (never include a body or a token)."""
import urllib.error

from ..errors import AppError


def map_http_error(exc: urllib.error.HTTPError, host_label: str, not_found: str | None = None) -> AppError:
    if exc.code == 401:
        return AppError(f"{host_label} rejected the token (401). Check that the PAT is valid and not expired.", 401)
    if exc.code in (403, 429):
        return AppError(f"{host_label} denied the request (rate limit or missing permission on the token).", 403)
    if exc.code == 404:
        return AppError(not_found or "Repository not found, or the token has no access to it.", 404)
    if exc.code == 409:
        return AppError("The repository is empty.", 409)
    return AppError(f"{host_label} returned an unexpected error ({exc.code}).", 502)


def unreachable(host_label: str) -> AppError:
    return AppError(f"Could not reach {host_label}. Check the URL and your network.", 502)
