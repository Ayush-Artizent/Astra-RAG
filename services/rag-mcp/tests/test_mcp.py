from rag_mcp.server import mcp

EXPECTED = {
    "search_code",
    "search_docs",
    "find_similar_requirements",
    "find_impacted",
    "list_repos",
    "submit_feedback",
}


async def test_tools_registered() -> None:
    names = {t.name for t in await mcp.list_tools()}
    assert names >= EXPECTED
