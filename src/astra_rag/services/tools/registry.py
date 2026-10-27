"""Explicit table of LLM-callable tools, their schemas and the dispatcher."""
from pydantic import ValidationError

from .. import token_store
from ..errors import AppError
from ..github_client import RepoRef
from . import document_context
from .base import Tool, json_schema, to_claude

TOOLS: dict[str, Tool] = {t.name: t for t in (document_context.tool,)}


def describe_tools(creds: tuple[RepoRef, str] | None = None) -> list[dict]:
    """Schemas for every tool (Claude format + `output_schema`); with a repo's creds, live hints are added."""
    described = []
    for tool in TOOLS.values():
        entry = {**to_claude(tool), "output_schema": json_schema(tool.result)}
        if creds and tool.refine_schema:
            try:
                tool.refine_schema(entry["input_schema"], *creds)
            except AppError:  # schema stays usable if GitHub is unreachable
                pass
        described.append(entry)
    return described


def run_tool(name: str, arguments: dict) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        raise AppError(f"Unknown tool '{name}'.")
    try:
        args = tool.args.model_validate(arguments or {})
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) if e["loc"] else "arguments" for e in exc.errors()})
        raise AppError(f"Invalid arguments for {name}: check " + ", ".join(fields) + ".") from None
    repo, token = token_store.get_credentials(args.owner, args.name)
    return tool.handler(repo, token, args).model_dump()
