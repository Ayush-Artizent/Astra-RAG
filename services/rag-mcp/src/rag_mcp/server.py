"""MCP server. Contains no retrieval logic: every tool forwards to rag-api through the SDK, so
REST, MCP and SDK can never drift apart.

Config (env): ``ASTRA_API_URL``, ``ASTRA_API_TOKEN``, optional ``ASTRA_MCP_TRANSPORT``
(``stdio`` default, or ``streamable-http``).
TODO(platform pod): for remote HTTP transport, forward the *caller's* bearer token per session
instead of a static service token, so tenant is still derived from the end credential.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from astra_rag_sdk import AstraRagClient
from rag_core.schemas import CallerInfo, DocType, EdgeKind, FeedbackLabel

mcp = MCPServer("astra-rag")


def _client() -> AstraRagClient:
    return AstraRagClient(
        os.environ.get("ASTRA_API_URL", "http://localhost:8080"),
        os.environ["ASTRA_API_TOKEN"],
        caller=CallerInfo(platform="mcp"),
    )


@mcp.tool()
async def search_code(
    query: str, repos: list[str] | None = None, languages: list[str] | None = None, k: int = 10
) -> dict[str, Any]:
    """Hybrid (keyword + semantic) search over indexed source code. Returns chunks with
    SHA-pinned citations. Use exact identifiers when you know them."""
    async with _client() as c:
        return (await c.search_code(query, repos=repos, languages=languages, k=k)).model_dump(
            mode="json"
        )


@mcp.tool()
async def search_docs(
    query: str, doc_types: list[DocType] | None = None, k: int = 10
) -> dict[str, Any]:
    """Search BRDs, ADRs, standards, specs and READMEs. Golden-repo docs rank higher."""
    async with _client() as c:
        return (await c.search_docs(query, doc_types=doc_types, k=k)).model_dump(mode="json")


@mcp.tool()
async def find_similar_requirements(text: str, k: int = 5) -> dict[str, Any]:
    """Find past BRDs/specs similar to a new requirement or ticket description."""
    async with _client() as c:
        return (await c.find_similar_requirements(text, k=k)).model_dump(mode="json")


@mcp.tool()
async def find_impacted(
    entities: list[str], depth: int = 2, kinds: list[EdgeKind] | None = None
) -> dict[str, Any]:
    """What depends on these repos/files/APIs? Edges carry confidence and source;
    weigh low-confidence edges accordingly."""
    async with _client() as c:
        return (await c.find_impacted(entities, depth=depth, kinds=kinds)).model_dump(mode="json")


@mcp.tool()
async def list_repos(query: str | None = None) -> dict[str, Any]:
    """List indexed repositories with their indexed SHA and freshness."""
    async with _client() as c:
        return (await c.list_repos(query)).model_dump(mode="json")


@mcp.tool()
async def submit_feedback(trace_id: str, label: FeedbackLabel, chunk_id: str | None = None) -> str:
    """Mark a retrieved chunk relevant/irrelevant, or report missing context, for a trace_id."""
    async with _client() as c:
        await c.submit_feedback(trace_id, label, chunk_id=chunk_id)
    return "ok"


def main() -> None:
    transport: Literal["stdio", "streamable-http"] = (
        "streamable-http" if os.environ.get("ASTRA_MCP_TRANSPORT") == "streamable-http" else "stdio"
    )
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
