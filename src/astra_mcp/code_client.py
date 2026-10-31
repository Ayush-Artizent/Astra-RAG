"""HTTP client for the code plane's internal API (`/internal/v1/code/query`, `/status`).

Every call carries a freshly signed envelope. The adapter takes org and project from it alone, so
nothing a caller sends can change which project is read.
"""
import httpx

from .config import Config
from .envelope import HEADER, new_request_id, sign
from .errors import PlaneError

QUERY_PATH = "/internal/v1/code/query"
STATUS_PATH = "/internal/v1/code/status"


def _problem(body: object, status: int) -> str:
    """An RFC 9457 problem as one safe line. `detail` is the adapter's own wording."""
    fallback = f"The code plane refused the call ({status})."
    if not isinstance(body, dict):
        return fallback
    message = str(body.get("detail") or body.get("title") or "").strip() or fallback
    code = body.get("error_code")
    return f"{message} [{code}]" if code else message


class CodeClient:
    def __init__(self, config: Config, client: httpx.AsyncClient | None = None):
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)

    async def query(self, body: dict) -> dict:
        """One code query. `plane_status` not_ready or degraded is an answer, not a failure."""
        return await self._request("POST", QUERY_PATH, json=body)

    async def status(self) -> dict:
        return await self._request("GET", STATUS_PATH)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        request_id = new_request_id()
        headers = {HEADER: sign(self._config, ["query"], request_id), "x-request-id": request_id}
        try:
            reply = await self._client.request(
                method, f"{self._config.code_url}{path}", headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise PlaneError(f"The code plane could not be reached ({type(exc).__name__}).") from None
        try:
            body = reply.json()
        except ValueError:
            raise PlaneError(f"The code plane answered {reply.status_code} with something other than JSON.") from None
        if reply.is_error:
            raise PlaneError(_problem(body, reply.status_code))
        return body if isinstance(body, dict) else {}
