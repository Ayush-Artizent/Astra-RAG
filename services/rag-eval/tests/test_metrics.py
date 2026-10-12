import pytest

from rag_eval.dataset import ExpectedSource
from rag_eval.harness import Report, gate
from rag_eval.metrics import Retrieved, context_precision, mrr, ndcg_at_k, recall_at_k

EXP = [ExpectedSource(repo="r", path="a.py", lines=(10, 20)), ExpectedSource(repo="r", path="b.md")]
GOT = [
    Retrieved("r", "x.py", (1, 5)),
    Retrieved("r", "a.py", (15, 30)),  # overlaps expected lines
    Retrieved("r", "a.py", (100, 120)),  # same file, wrong lines
    Retrieved("r", "b.md", (1, 3)),
]


def test_recall_and_mrr() -> None:
    assert recall_at_k(GOT, EXP, 2) == 0.5
    assert recall_at_k(GOT, EXP, 4) == 1.0
    assert mrr(GOT, EXP) == 0.5


def test_ndcg_perfect_and_bounded() -> None:
    perfect = [Retrieved("r", "a.py", (10, 20)), Retrieved("r", "b.md", (1, 2))]
    assert ndcg_at_k(perfect, EXP, 10) == pytest.approx(1.0)
    assert 0 < ndcg_at_k(GOT, EXP, 10) < 1


def test_context_precision() -> None:
    assert context_precision(GOT, EXP) == 0.5


def test_gate() -> None:
    base = Report(
        index_version=1,
        n_cases=1,
        aggregate={"recall@10": 0.8, "mrr": 0.5, "ndcg@10": 0.6},
        by_tag={},
        cases=[],
    )
    ok = base.model_copy(update={"aggregate": {"recall@10": 0.79, "mrr": 0.5, "ndcg@10": 0.6}})
    bad = base.model_copy(update={"aggregate": {"recall@10": 0.7, "mrr": 0.5, "ndcg@10": 0.6}})
    assert gate(base, ok, 0.02) == []
    assert gate(base, bad, 0.02)
