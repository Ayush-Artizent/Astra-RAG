from rag_core.ids import chunk_id, content_hash
from rag_core.provenance import deep_link
from rag_core.schemas import GitHost
from rag_core.text import tokenize_identifiers


def test_chunk_id_is_deterministic_and_tenant_scoped() -> None:
    h = content_hash("def f(): pass")
    assert chunk_id("t1", "r", "p.py", "f", h) == chunk_id("t1", "r", "p.py", "f", h)
    assert chunk_id("t1", "r", "p.py", "f", h) != chunk_id("t2", "r", "p.py", "f", h)


def test_identifier_tokenizer_keeps_original_and_splits() -> None:
    toks = tokenize_identifiers("RefundPolicy.is_eligible getHTTPResponse")
    for expected in [
        "refundpolicy.is_eligible",
        "refund",
        "policy",
        "is",
        "eligible",
        "gethttpresponse",
        "get",
        "http",
        "response",
    ]:
        assert expected in toks


def test_deep_links_are_sha_pinned() -> None:
    gl = deep_link(GitHost.GITLAB, "https://gitlab.x/g/repo", "9fc2", "src/a.py", 42, 97)
    assert gl == "https://gitlab.x/g/repo/-/blob/9fc2/src/a.py#L42-97"
    az = deep_link(
        GitHost.AZURE_REPOS, "https://dev.azure.com/o/p/_git/r", "9fc2", "src/a.py", 1, 2
    )
    assert "version=GC9fc2" in az
    assert "line=1" in az
