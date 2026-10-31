"""Turns the doc plane's Claude-format tool entries into MCP tools."""
from mcp_types import Tool as MCPTool

# Bound at spawn and injected on the way out, so the caller neither supplies it nor sees it: an
# agent then cannot name another project.
HIDDEN_ARGUMENT = "project_id"


def hide_project_id(schema: dict) -> dict:
    """The same schema without the project argument, left otherwise untouched."""
    properties = {k: v for k, v in (schema.get("properties") or {}).items() if k != HIDDEN_ARGUMENT}
    required = [name for name in (schema.get("required") or []) if name != HIDDEN_ARGUMENT]
    hidden = {**schema, "properties": properties}
    if required:
        hidden["required"] = required
    else:
        hidden.pop("required", None)
    return hidden


def to_mcp_tool(entry: dict) -> MCPTool:
    """One `GET /api/tools` entry as an MCP tool. `input_schema` is the plane's, minus the project."""
    return MCPTool(
        name=entry["name"],
        description=entry.get("description") or None,
        input_schema=hide_project_id(entry.get("input_schema") or {"type": "object", "properties": {}}),
    )
