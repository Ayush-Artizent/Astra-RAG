"""Thin HTTP layer for the demo page: the page itself and the JSON it calls."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ..config import Config
from . import service
from .paths import TEMPLATES_DIR
from .session import McpSession, SessionError

router = APIRouter()


class ToolCall(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _state(request: Request) -> tuple[Config, McpSession]:
    return request.app.state.config, request.app.state.session


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    config, _ = _state(request)
    return templates.TemplateResponse(request, "index.html", {"project_id": config.project_id,
                                                              "org_id": config.org_id})


@router.get("/api/status")
async def status(request: Request):
    config, session = _state(request)
    return {"ok": True, **await service.status(config, session)}


# Plain `def`: talking to the child process blocks, so FastAPI runs it in a worker thread.
@router.get("/api/tools")
def tools(request: Request):
    _, session = _state(request)
    try:
        tools = [{**tool, "plane": service.plane_of(tool.get("name", ""))} for tool in session.list_tools()]
        return {"ok": True, "tools": tools, "server": session.server_info,
                "instructions": session.instructions}
    except SessionError as err:
        return {"ok": False, "error": str(err)}


@router.post("/api/session/restart")
def restart(request: Request):
    _, session = _state(request)
    try:
        session.restart()
    except SessionError as err:
        return {"ok": False, "error": str(err)}
    return {"ok": True, "server": session.server_info}


@router.post("/api/call")
def call_tool(request: Request, body: ToolCall):
    _, session = _state(request)
    try:
        result = session.call_tool(body.name, body.arguments)
    except SessionError as err:
        return {"ok": False, "error": str(err)}
    return {"ok": True, **service.split_result(body.name, result)}
