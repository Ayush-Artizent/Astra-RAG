"""Explicit table of LLM-callable tools, their schemas and the dispatcher."""
from pydantic import ValidationError

from ..errors import AppError
from . import document_context, search_project_data
from .base import DATA_NOTICE, Tool, to_claude

TOOLS: dict[str, Tool] = {t.name: t for t in (document_context.tool, search_project_data.tool)}


def describe_tools(project_id: str | None = None) -> list[dict]:
    """Claude-format schemas; for a project, live hints (the `doc_type` enum) are added."""
    described = []
    for tool in TOOLS.values():
        entry = to_claude(tool)
        if project_id and tool.refine_schema:
            tool.refine_schema(entry["input_schema"], project_id)
        described.append(entry)
    return described


def run_tool(name: str, arguments: dict) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        raise AppError(f"Unknown tool '{name}'.", 404)
    try:
        args = tool.args.model_validate(arguments or {})
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) if e["loc"] else "arguments" for e in exc.errors()})
        raise AppError(f"Invalid arguments for {name}: check " + ", ".join(fields) + ".", 422) from None
    return {"notice": DATA_NOTICE, "data": tool.handler(args)}
