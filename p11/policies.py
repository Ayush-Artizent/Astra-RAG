"""Replay rerank cut-off policies on a saved run (`run_eval --json`), without models or Qdrant.

    uv run python -m p11.policies p11/out/trace.json

A policy keeps a reranked hit when `score >= abs_min` and `score >= top_score - margin` (margin None = no relative cut).
The kept hits are then fitted to the token budget as in the app, and scored with the same evidence formula as run_eval.
"""
import json
import sys

from p11 import metrics as m


def replay(row: dict, q: dict, abs_min: float, margin: float | None, limit: int, weak: int = 0) -> float:
    """Evidence this question would earn under the policy. `weak` = how many hits below the floor are kept, flagged
    low-confidence, after the confident ones; they count as evidence, but a no-answer question is only answered by a confident hit."""
    trace = row["trace"]
    top = trace[0]["score"] if trace else None
    kept = [t for t in trace if t["score"] >= abs_min and (margin is None or t["score"] >= top - margin)]
    kept += [t for t in trace if t["score"] < abs_min][:weak]
    room, final = limit - row["overhead_tokens"], []
    for t in kept:  # the first hit that does not fit ends the list, as in Budget.take_items
        if t["tokens"] > room:
            break
        room -= t["tokens"]
        final.append(t)
    if q.get("negative"):
        return m.evidence_score(q, None, None, answered=any(t["score"] >= abs_min for t in final))
    ranks = [next((i for i, t in enumerate(final, 1) if n in t["sources"]), None) for n in range(len(q["sources"]))]
    facts = {n for t in final for n in t["facts"]}
    fact_share = len(facts) / len(q["facts"]) if q["facts"] else None
    return m.evidence_score(q, m.recall_at(ranks, q.get("match", "all"), None), fact_share, answered=bool(final))


def evaluate(run: dict, questions: list[dict], abs_min: float, margin: float | None, weak: int = 0) -> dict:
    by_id = {q["id"]: q for q in questions}
    rows = [r for r in run["questions"] if "trace" in r]
    scores = {r["id"]: replay(r, by_id[r["id"]], abs_min, margin, run["config"]["budget"], weak) for r in rows}
    return {"evidence": m.mean(scores.values()), "scores": scores}


def main(path: str) -> None:
    import yaml
    from pathlib import Path

    run = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = yaml.safe_load((Path(__file__).parent / "questions.yaml").read_text(encoding="utf-8"))["questions"]
    current = evaluate(run, questions, run["config"]["min_score"], None)
    recorded = m.mean(r["evidence"] for r in run["questions"] if "trace" in r)
    print(f"Replay check: current policy replays to evidence {current['evidence']:.3f}, the run recorded {recorded:.3f}\n")

    margins = [None, 10, 8, 6, 5, 4, 3, 2]
    floors = [-12, -10, -9, -8, -7, -6.5, -6, -5]
    print("Evidence (mean over all questions; the no-answer question counts 1 when nothing is returned)")
    print("margin \\ floor " + "".join(f"{f:>7}" for f in floors))
    for margin in margins:
        print(f"{'none' if margin is None else margin:>14} " + "".join(
            f"{evaluate(run, questions, f, margin)['evidence']:7.3f}" for f in floors))

    counts = (0, 2, 3, 5, 8, 10, 30)
    print("\nConfident hits (>= floor) plus the N best weak hits, flagged low-confidence")
    print("floor \\ N " + "".join(f"{n:>7}" for n in counts))
    for f in (-6, -5, -4, -3, 0):
        print(f"{f:>9} " + "".join(f"{evaluate(run, questions, f, None, n)['evidence']:7.3f}" for n in counts))

    rows = [r for r in run["questions"] if "trace" in r]
    print("\nTop rerank score per question (what a cut has to work with):")
    for r in sorted(rows, key=lambda r: r["trace"][0]["score"]):
        best = next((t["score"] for t in r["trace"] if t["sources"]), None)
        print(f"  {r['id']}  top {r['trace'][0]['score']:7.2f}   best expected source {best if best is None else format(best, '7.2f')}"
              f"   evidence now {r['evidence']:.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
