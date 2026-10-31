"""HTTP client for the doc plane's tool API: `GET /api/tools` and `POST /api/tools/invoke`.

The plane owns the tool list, the schemas and the work behind them. Nothing is declared here, so a
tool the doc team adds appears without a change on this side.
"""
import httpx

from .config import Config
from .errors import PlaneError

__all__ = ["DocClient", "PlaneError"]


class DocClient:
    def __init__(self, config: Config, client: httpx.AsyncClient | None = None):
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)

    async def list_tools(self) -> list[dict]:
        """The plane's own entries. Asking by project fills in the live `doc_type` enum."""
        body = await self._request("GET", "/api/tools", params={"project_id": self._config.project_id})
        tools = body.get("tools")
        return tools if isinstance(tools, list) else []

    async def invoke(self, name: str, arguments: dict) -> dict:
        """Run one tool. The project is this server's, never the caller's."""
        payload = {"name": name, "arguments": {**arguments, "project_id": self._config.project_id}}
        body = await self._request("POST", "/api/tools/invoke", json=payload)
        result = body.get("result")
        return result if isinstance(result, dict) else {}

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            reply = await self._client.request(method, f"{self._config.doc_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            # The exception text can carry the URL; the type name is enough to act on.
            raise PlaneError(f"The document plane could not be reached ({type(exc).__name__}).") from None
        try:
            body = reply.json()
        except ValueError:
            raise PlaneError(f"The document plane answered {reply.status_code} with something other than JSON.") from None
        if not isinstance(body, dict):
            raise PlaneError("The document plane answered in an unexpected shape.")
        if reply.is_error or body.get("ok") is False:
            # `error` is already an AppError message, written to be shown.
            raise PlaneError(str(body.get("error") or f"The document plane refused the call ({reply.status_code})."))
        return body
