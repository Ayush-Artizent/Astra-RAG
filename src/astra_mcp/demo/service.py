"""Facts for the page: whether each plane answers, and a tool result split into its parts."""
import json

import httpx

from ..config import Config
from ..doc_client import DocClient
from ..errors import PlaneError
from ..tools_code import TOOLS as CODE_TOOLS
from .session import McpSession

HEALTH_PATH = "/internal/v1/health"


async def document_plane(config: Config) -> dict:
    """Listing tools is the honest health check: it is exactly what the server needs to work."""
    try:
        tools = await DocClient(config).list_tools()
    except PlaneError as err:
        return {"ok": False, "detail": str(err)}
    return {"ok": True, "detail": f"{len(tools)} tool(s) offered"}


async def code_plane(config: Config) -> dict:
    """`/internal/v1/health` needs no envelope, so it answers even when a key is wrong."""
    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            reply = await client.get(f"{config.code_url}{HEALTH_PATH}")
            body = reply.json()
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"Not reachable ({type(exc).__name__})."}
    except ValueError:
        return {"ok": False, "detail": "Answered with something other than JSON."}
    if reply.is_error:
        return {"ok": False, "detail": f"Answered {reply.status_code}."}
    return {
        "ok": body.get("status") == "ok",
        "detail": f"CodeGraph {body.get('codegraph_version')} on Node {body.get('node_version')}",
        "wal_probe": body.get("wal_probe"),
    }


async def status(config: Config, session: McpSession) -> dict:
    return {
        "project": {"org_id": config.org_id, "project_id": config.project_id},
        "document": await document_plane(config),
        "code": await code_plane(config),
        "session": {
            "running": session.running(),
            "server": session.server_info,
            "error": session.start_error,
        },
    }


STATUS_TOOL = "code_index_status"


def plane_of(name: str) -> str:
    """Which plane answers this tool, for the page's badge. Status is the code plane's too."""
    return "code" if name in CODE_TOOLS else "documents"


def kind_of(name: str) -> str:
    """Which renderer the page should use. Status is its own shape, not a query result."""
    if name == STATUS_TOOL:
        return "status"
    return "code" if name in CODE_TOOLS else "document"


def split_result(name: str, result: dict) -> dict:
    """A `tools/call` result as the page wants it: the note, then the payload.

    The server puts a note in its own block in front of the payload, so a result with more than one
    block has one. An error result carries a message rather than JSON, which is why `payload` can be
    null while `text` still holds something worth showing.
    """
    texts = [b.get("text") or "" for b in (result.get("content") or []) if b.get("type") == "text"]
    raw = texts[-1] if texts else ""
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = None
    return {
        "is_error": bool(result.get("isError")),
        "note": texts[0] if len(texts) > 1 else None,
        "payload": payload,
        "text": raw,
        "kind": kind_of(name),
    }
