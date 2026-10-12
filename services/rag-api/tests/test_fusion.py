from rag_api.retrieval.fusion import dedupe, pack, rrf
from rag_core.interfaces import ScoredHit, SearchMode
from rag_core.schemas import Chunk


def c(
    cid: str,
    path: str = "a.py",
    start: int = 1,
    end: int = 10,
    text: str = "x" * 40,
    h: str | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=cid,
        tenant_id="t",
        repo="r",
        path=path,
        commit_sha="s",
        start_line=start,
        end_line=end,
        content_hash=h or cid,
        text=text,
    )


def test_rrf_rewards_agreement() -> None:
    lex = [ScoredHit(c("a"), 9, SearchMode.LEXICAL), ScoredHit(c("b"), 5, SearchMode.LEXICAL)]
    vec = [ScoredHit(c("b"), 0.9, SearchMode.VECTOR), ScoredHit(c("z"), 0.8, SearchMode.VECTOR)]
    order = [ch.chunk_id for ch, _ in rrf([lex, vec])]
    assert order[0] == "b"


def test_dedupe_drops_same_content_and_overlaps() -> None:
    out = dedupe(
        [
            c("a", h="H"),
            c("b", path="other.py", h="H"),
            c("c", start=2, end=9),
            c("d", start=50, end=60),
        ]
    )
    assert [x.chunk_id for x in out] == ["a", "d"]


def test_pack_respects_budget_and_diversity() -> None:
    chunks = [c(f"s{i}", start=i * 20 + 1, end=i * 20 + 5) for i in range(5)] + [
        c("o", path="b.py")
    ]
    out = pack(chunks, k=4, token_budget=10_000, max_per_file=3)
    assert "o" in [x.chunk_id for x in out]  # other file promoted over a 4th same-file chunk
    assert len(pack(chunks, k=10, token_budget=25)) == 2  # 10 tokens each
