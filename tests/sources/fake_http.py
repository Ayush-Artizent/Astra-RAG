"""A stand-in for urllib's urlopen so adapter tests need no network."""
import io
import urllib.error
from unittest import mock


class FakeHttp:
    """Routes match when their text is in the request URL; the longest (most specific) match wins."""

    def __init__(self):
        self.routes: list[tuple[str, object]] = []
        self._override = None  # an outcome that answers every request, e.g. a host-wide 401
        self.requests: list = []
        self._patch = mock.patch("astra_rag.services.sources.http.urllib.request.urlopen", side_effect=self)

    def add(self, contains: str, body: bytes | str = b"", status: int = 200) -> None:
        self.routes.append((contains, (status, body.encode() if isinstance(body, str) else body)))

    def fail(self, exc: Exception, contains: str = "") -> None:
        self.routes.append((contains, exc))

    def fail_with_status(self, status: int) -> None:
        self._override = (status, b"")

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        matches = [(c, o) for c, o in self.routes if c in request.full_url]
        if not matches and self._override is None:
            raise AssertionError(f"unexpected request: {request.full_url}")
        outcome = self._override or max(matches, key=lambda m: len(m[0]))[1]
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, io.BytesIO(b"secret body"))
        return io.BytesIO(body)

    def last_headers(self) -> dict[str, str]:
        return {k.lower(): v for k, v in self.requests[-1].header_items()}

    def __enter__(self):
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
