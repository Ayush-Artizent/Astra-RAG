"""Shared building blocks for LLM-callable tools: the Tool definition and schema renderers."""
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field

from ..github_client import RepoRef

NAME_PATTERN = r"^[\w.-]+$"


class RepoArgs(BaseModel):
    """Base for tool arguments that act on a connected repo; URL + PAT are looked up from these."""
    owner: str = Field(
        min_length=1, max_length=100, pattern=NAME_PATTERN,
        description="GitHub owner (user or org) of the project's golden repo.",
    )
    name: str = Field(
        min_length=1, max_length=100, pattern=NAME_PATTERN,
        description="Name of the project's golden repo.",
    )


@dataclass(frozen=True)
class Tool:
    """One tool's single definition; each tool directory exports one `tool`."""
    name: str
    description: str
    args: type[RepoArgs]
    result: type[BaseModel]
    handler: Callable[[RepoRef, str, Any], BaseModel]  # (repo, token, validated args) -> result
    refine_schema: Callable[[dict, RepoRef, str], None] | None = None  # e.g. add an enum from live data


def json_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


def to_claude(tool: Tool) -> dict:
    """Claude tool-use format."""
    return {"name": tool.name, "description": tool.description, "input_schema": json_schema(tool.args)}


def to_mcp(tool: Tool) -> dict:
    """Model Context Protocol tool format."""
    return {"name": tool.name, "description": tool.description,
            "inputSchema": json_schema(tool.args), "outputSchema": json_schema(tool.result)}
