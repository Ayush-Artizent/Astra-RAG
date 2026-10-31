"""A stand-in for the doc plane, so the MCP tests need no network and no running server."""
import json

import httpx

from astra_mcp.config import Config

DOC_TOOL = {
    "name": "get_document_context",
    "description": "Get what is needed to draft a project document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "description": "The ASTRA project's id."},
            "doc_type": {"type": "string", "enum": ["BRD", "SPEC"]},
            "text": {"type": "string", "maxLength": 4000},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["project_id", "doc_type", "text"],
    },
}

NOTICE = "Everything under `data` was read from the project's golden repository."


def a_config(**overrides) -> Config:
    fields = {
        "org_id": "nous", "project_id": "devx-123",
        "doc_url": "http://127.0.0.1:5000", "code_url": "http://127.0.0.1:8091",
        "envelope_key": "k" * 16, "timeout_ms": 30_000,
    }
    fields.update(overrides)
    return Config(**fields)


class FakeDocPlane:
    """Answers the two tool endpoints and records what it was asked."""

    def __init__(self, tools: list[dict] | None = None, data: dict | None = None):
        self.tools = [DOC_TOOL] if tools is None else tools
        self.data = {"rules": []} if data is None else data
        self.requests: list[httpx.Request] = []
        self.error: tuple[int, str] | None = None  # (status, message) for an AppError reply
        self.raises: Exception | None = None
        self.raw: tuple[int, str] | None = None  # a reply that is not JSON

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def last_body(self) -> dict:
        return json.loads(self.requests[-1].content)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        if self.raw is not None:
            status, text = self.raw
            return httpx.Response(status, text=text)
        if self.error is not None:
            status, message = self.error
            return httpx.Response(status, json={"ok": False, "error": message})
        if request.url.path == "/api/tools":
            return httpx.Response(200, json={"ok": True, "tools": self.tools})
        if request.url.path == "/api/tools/invoke":
            return httpx.Response(200, json={"ok": True, "result": {"notice": NOTICE, "data": self.data}})
        return httpx.Response(404, json={"ok": False, "error": "Unknown route."})


QUERY_RESULT = {
    "request_id": "r-1", "plane_status": "ok",
    "snapshot": {"commit_sha": "abc123", "index_time": "2026-10-30T00:00:00Z",
                 "index_state": "complete", "sync_in_progress": False},
    "resolved_symbols": [{"input": "TokenService.issue", "status": "exact"}],
    "results": [{"plane_rank": 1, "kind": "method", "citation": "src/auth/token.ts:42-67",
                 "provenance": {"file_path": "src/auth/token.ts", "line_start": 42, "line_end": 67}}],
    "truncated": False,
}

STATUS_RESULT = {"state": "ready", "last_synced_sha": "abc123", "index_lag_seconds": 0,
                 "error": None, "active_job": None, "disk": None, "pruned_at": None}


class FakeCodePlane:
    """Answers the adapter's query and status endpoints and keeps what it was sent."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []
        self.problem: tuple[int, dict] | None = None  # (status, RFC 9457 body)
        self.raises: Exception | None = None
        self.query_result = QUERY_RESULT

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def envelope_header(self) -> str:
        return self.requests[-1].headers.get("x-astra-envelope", "")

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        if self.problem is not None:
            status, body = self.problem
            return httpx.Response(status, json=body)
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json=STATUS_RESULT)
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json=self.query_result)
