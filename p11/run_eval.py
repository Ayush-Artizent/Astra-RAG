"""P11 evaluation: run the question set through the real pipeline and report metrics per stage plus a combined score.

Needs what the app needs: Qdrant up (`docker compose up -d qdrant`), the repo connected and indexed (`data/astra.db`), a project
bound to it, the saved PAT in `.env` (the rules come live from the host) and the local models in `.cache/fastembed`.

    uv run python -m p11.run_eval                      # report
    uv run python -m p11.run_eval --json p11/out/base.json
    uv run python -m p11.run_eval --baseline p11/out/base.json   # exit 1 on a regression
    uv run python -m p11.run_eval --candidates 50 --min-score -3 --budget 4000   # try other settings

Stage metrics are read from the real calls (`pipeline.search`, `knowledge.rerank`) made inside one `service.get_context`.
"""
import argparse
import json
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

from p11 import metrics as m

HERE = Path(__file__).parent


def _chunk(hit: dict) -> dict:
    """A raw search hit or a knowledge item, as the metric functions see it."""
    return {"file": hit.get("path") or hit.get("file"), "heading_path": hit.get("heading_path") or [],
            "text": hit.get("text") or ""}


@contextmanager
def capture():
    """Record what the search and the rerank returned during one get_context call."""
    from astra_rag.services.context import knowledge
    from astra_rag.services.ingestion import pipeline

    seen: dict = {}
    real_search, real_rerank = pipeline.search, knowledge.rerank

    def search(*args, **kwargs):
        seen["hits"] = real_search(*args, **kwargs)
        return seen["hits"]

    def rerank(*args, **kwargs):
        seen["reranked"], seen["rerank"] = real_rerank(*args, **kwargs)
        return seen["reranked"], seen["rerank"]

    pipeline.search, knowledge.rerank = search, rerank
    try:
        yield seen
    finally:
        pipeline.search, knowledge.rerank = real_search, real_rerank


def indexed_chunks(slug: str) -> list[dict]:
    """Every chunk of the repo's current index (to check the question set against what is really there)."""
    from astra_rag.services.ingestion.store import QdrantStore, collection_name

    store = QdrantStore()
    store.ping()
    out, offset = [], None
    while True:
        points, offset = store.client.scroll(collection_name(slug), limit=256, offset=offset,
                                             with_payload=True, with_vectors=False)
        out += [_chunk(p.payload or {}) for p in points]
        if offset is None:
            return out


def check_specs(questions: list[dict], chunks: list[dict]) -> list[str]:
    """Source specs that match no indexed chunk: the spec is wrong or the data changed, not a retrieval miss."""
    return [f"{q['id']}: source {s} matches no indexed chunk"
            for q in questions for s in q.get("sources", []) if not any(m.source_matches(s, c) for c in chunks)]


def prepare_models(timeout: float) -> None:
    from astra_rag.services import local_models
    from astra_rag.services.context import rerank
    from astra_rag.services.ingestion import pipeline

    local_models.wait_ready(("embedder", "reranker"), timeout)
    pipeline.get_embedder().embed_query("warm up")
    rerank.get_reranker().score("warm up", ["warm up", "warm up too"])


def _trace(q: dict, reranked: list[dict]) -> list[dict]:
    """Per reranked hit, best first: its score, which expected sources and facts it carries, its token cost."""
    from astra_rag.services.ingestion.tokens import count_tokens

    specs, facts = q.get("sources", []), q.get("facts", [])
    return [{"score": round(i["rerank_score"], 3), "tokens": count_tokens(i["text"]),
             "sources": [n for n, s in enumerate(specs) if m.source_matches(s, _chunk(i))],
             "facts": [n for n, f in enumerate(facts) if m.norm(f) in m.norm(i["text"])]} for i in reranked]


def run_question(q: dict, ctx_args: dict, cfg: dict) -> dict:
    from astra_rag.services.context import knowledge, service
    from astra_rag.services.errors import AppError
    from astra_rag.services.ingestion.tokens import count_tokens

    mode = q.get("match", "all")
    row = {"id": q["id"], "type": q.get("type"), "difficulty": q.get("difficulty"), "negative": bool(q.get("negative"))}
    started = time.perf_counter()
    try:
        with capture() as seen:
            ctx = service.get_context(**ctx_args, text=q["text"])
    except AppError as exc:
        return {**row, "error": exc.message, "evidence": 0.0, "degraded": True}
    row["text"] = q["text"]
    row["seconds"] = round(time.perf_counter() - started, 2)

    status = ctx["status"]
    candidates = [_chunk(h) for h in seen.get("hits", [])]
    rerank_ok = seen.get("rerank") == "ok"
    reranked = [_chunk(i) for i in seen.get("reranked", [])] if rerank_ok else []
    kept = [_chunk(i) for i in seen.get("reranked", []) if i["rerank_score"] >= knowledge.RERANK_MIN_SCORE] if rerank_ok else []
    final = [_chunk(i) for i in ctx["knowledge"]["items"]]
    row.update(knowledge_status=status["knowledge"], rerank_status=status["rerank"], candidates=len(candidates),
               final_items=len(final), confident_items=sum(not i["low_confidence"] for i in ctx["knowledge"]["items"]),
               tokens_used=ctx["budget"]["used"],
               knowledge_truncated=ctx["knowledge"]["truncated"],
               degraded=status["rerank"].startswith("skipped") or status["knowledge"] in ("no_index",)
               or status["knowledge"].startswith("unavailable"))

    if rerank_ok:  # enough to replay other cut-off policies offline (p11/policies.py)
        row["trace"] = _trace(q, seen["reranked"])
        row["overhead_tokens"] = ctx["budget"]["used"] - sum(count_tokens(i["text"]) for i in ctx["knowledge"]["items"])
    specs = q.get("sources", [])
    if row["negative"]:
        row["evidence"] = m.evidence_score(q, None, None, answered=row["confident_items"] > 0)
        return row
    r_cand, r_rer = m.source_ranks(specs, candidates), m.source_ranks(specs, reranked)
    r_kept, r_final = m.source_ranks(specs, kept), m.source_ranks(specs, final)
    facts = m.fact_recall(q.get("facts", []), final)
    row.update(
        recall_10=m.recall_at(r_cand, mode, 10), recall_all=m.recall_at(r_cand, mode, None),
        rr=m.reciprocal_rank(r_rer) if rerank_ok else None, recall_5=m.recall_at(r_rer, mode, 5) if rerank_ok else None,
        dropped=m.dropped_relevant(r_rer, r_kept) if rerank_ok else None,
        recall_kept=m.recall_at(r_kept, mode, None) if rerank_ok else None,
        recall_budget=m.recall_at(r_final, mode, None), facts_budget=facts,
        ranks={"candidates": r_cand, "reranked": r_rer if rerank_ok else None, "final": r_final})
    row["evidence"] = m.evidence_score(q, row["recall_budget"], facts, answered=bool(final))
    return row


def run_rule_case(case: dict, project_id: str) -> dict:
    from astra_rag.services.context import service
    from astra_rag.services.errors import AppError

    try:
        out = service.preview(project_id, case["doc_type"], case.get("stage"), case.get("tags", []))
    except AppError as exc:
        return {"id": case["id"], "error": exc.message, "f1": 0.0, "precision": 0.0, "recall": 0.0}
    scoped = [r for r in out["rules"] if r["matched_on"] != "always"]
    scores = m.rule_scores(case["rules"], scoped)
    return {"id": case["id"], **scores, "selected": len(scoped), "template": m.template_ok(case.get("template"), out["template"])}


def summarize(rows: list[dict], rule_rows: list[dict], cfg: dict) -> dict:
    positive = [r for r in rows if not r["negative"] and "error" not in r]
    negative = [r for r in rows if r["negative"] and "error" not in r]
    dropped = [r["dropped"] for r in positive if r.get("dropped")]
    times = [r["seconds"] for r in rows if "seconds" in r]
    degraded_rate = m.mean(float(r["degraded"]) for r in rows)
    evidence = m.mean(r["evidence"] for r in rows)
    rules = m.mean(r["f1"] for r in rule_rows)
    by_difficulty = {d: m.mean(r["evidence"] for r in rows if r.get("difficulty") == d)
                     for d in ("easy", "medium", "hard")}
    return {
        "retrieval": {f"recall@10": m.mean(r.get("recall_10") for r in positive),
                      f"recall@{cfg['candidates']}": m.mean(r.get("recall_all") for r in positive)},
        "rerank": {"mrr": m.mean(r.get("rr") for r in positive), "recall@5": m.mean(r.get("recall_5") for r in positive),
                   "dropped_relevant_rate": (sum(d[0] for d in dropped) / sum(d[1] for d in dropped)) if dropped and sum(d[1] for d in dropped) else None,
                   "recall_after_threshold": m.mean(r.get("recall_kept") for r in positive)},
        "budget": {"recall@budget": m.mean(r.get("recall_budget") for r in positive),
                   "fact_recall@budget": m.mean(r.get("facts_budget") for r in positive),
                   "knowledge_truncated_rate": m.mean(float(r["knowledge_truncated"]) for r in positive if "knowledge_truncated" in r)},
        "rules": {"precision": m.mean(r["precision"] for r in rule_rows), "recall": m.mean(r["recall"] for r in rule_rows),
                  "f1": rules, "template_accuracy": m.mean(float(r["template"]) for r in rule_rows if r.get("template") is not None)},
        "degraded": {"degraded_rate": degraded_rate,
                     "rerank_skipped_rate": m.mean(float(r.get("rerank_status", "").startswith("skipped")) for r in rows),
                     "no_relevant_match_rate": m.mean(float(r.get("knowledge_status") == "no_relevant_match") for r in positive),
                     "no_answer_correct_rate": m.mean(float(r["confident_items"] == 0) for r in negative),
                     "errors": sum("error" in r for r in rows)},
        "latency_seconds": {"median": statistics.median(times) if times else None, "max": max(times) if times else None},
        "evidence_by_difficulty": by_difficulty,
        "evidence": evidence, "rules_f1": rules,
        "combined": m.combined(evidence, rules, degraded_rate),
    }


def fmt(value) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def table(headers: list[str], body: list[list]) -> str:
    cells = [headers] + [[fmt(c) for c in row] for row in body]
    widths = [max(len(str(r[i])) for r in cells) for i in range(len(headers))]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in cells]
    return "\n".join([lines[0], "  ".join("-" * w for w in widths), *lines[1:]])


def report(rows: list[dict], rule_rows: list[dict], summary: dict, cfg: dict, warnings: list[str]) -> None:
    n = cfg["candidates"]
    print(f"\nP11 evaluation | repo {cfg['slug']} | index commit {cfg['index_commit']}")
    print(f"settings: candidates={n} min_score={cfg['min_score']} budget={cfg['budget']} rerank_timeout={cfg['rerank_timeout']}s\n")
    for w in warnings:
        print(f"WARNING {w}")
    if warnings:
        print()
    print("Questions (r@k = share of expected sources found; rr = reciprocal rank after rerank; drop = relevant hit below the floor, so only low-confidence at best)")
    print(table(["id", "diff", f"r@10", f"r@{n}", "rr", "r@5", "drop", "r@budget", "facts", "evid", "rerank", "knowledge"], [
        [r["id"], r.get("difficulty"), r.get("recall_10"), r.get("recall_all"), r.get("rr"), r.get("recall_5"),
         f"{r['dropped'][0]}/{r['dropped'][1]}" if r.get("dropped") else None, r.get("recall_budget"),
         r.get("facts_budget"), r["evidence"], r.get("rerank_status", "error"), r.get("error") or r.get("knowledge_status")]
        for r in rows]))
    if rule_rows:
        print("\nRule and template cases (scope-selected rules only)")
        print(table(["id", "precision", "recall", "f1", "selected", "template", "missing", "unexpected"], [
            [r["id"], r["precision"], r["recall"], r["f1"], r.get("selected"), r.get("template"),
             ",".join(r.get("missing", [])) or "-", ",".join(r.get("unexpected", [])) or "-"] for r in rule_rows]))
    print("\nStage metrics")
    stages = [("retrieval", "retrieval"), ("rerank", "rerank"), ("budget", "budget"), ("rules + template", "rules"), ("degraded modes", "degraded")]
    print(table(["stage", "metric", "value"], [[label, k, v] for label, key in stages for k, v in summary[key].items()]))
    print("\nEvidence by difficulty: " + ", ".join(f"{d}={fmt(v)}" for d, v in summary["evidence_by_difficulty"].items()))
    lat = summary["latency_seconds"]
    print(f"Latency per request: median {fmt(lat['median'])} s, max {fmt(lat['max'])} s")
    print(f"\nCOMBINED SCORE = {fmt(summary['combined'])}   "
          f"(0.6 x evidence {fmt(summary['evidence'])} + 0.3 x rules F1 {fmt(summary['rules_f1'])} "
          f"+ 0.1 x (1 - degraded {fmt(summary['degraded']['degraded_rate'])}))")


def compare(baseline: dict, rows: list[dict], rule_rows: list[dict], summary: dict, tolerance: float) -> list[str]:
    """Regressions against a saved run: any question or rule case that got worse, or a combined score drop beyond the tolerance."""
    bad = []
    before = {r["id"]: r for r in baseline["questions"]}
    bad += [f"{r['id']}: evidence {before[r['id']]['evidence']:.2f} -> {r['evidence']:.2f}"
            for r in rows if r["id"] in before and r["evidence"] < before[r["id"]]["evidence"] - 1e-9]
    before = {r["id"]: r for r in baseline["rule_cases"]}
    bad += [f"{r['id']}: rules F1 {before[r['id']]['f1']:.2f} -> {r['f1']:.2f}"
            for r in rule_rows if r["id"] in before and r["f1"] < before[r["id"]]["f1"] - 1e-9]
    old, new = baseline["summary"]["combined"], summary["combined"]
    if old is not None and new is not None and new < old - tolerance:
        bad.append(f"combined score {old:.3f} -> {new:.3f} (tolerance {tolerance})")
    return bad


def main(argv: list[str] | None = None) -> int:
    from astra_rag import config
    from astra_rag.services.context import knowledge, rerank
    from astra_rag.services.errors import AppError
    from astra_rag.services.registry import repos

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", default=str(HERE / "questions.yaml"))
    ap.add_argument("--slug", help="repo slug (default: the one in the question file)")
    ap.add_argument("--project-id", help="a project bound to the repo (default: the first bound one)")
    ap.add_argument("--only", nargs="*", help="run only these question / rule case ids")
    ap.add_argument("--skip-rules", action="store_true", help="skip the rule and template cases (no host access needed)")
    ap.add_argument("--budget", type=int, default=config.CONTEXT_BUDGET_TOKENS)
    ap.add_argument("--candidates", type=int, default=config.KNOWLEDGE_CANDIDATES)
    ap.add_argument("--min-score", type=float, default=config.RERANK_MIN_SCORE)
    ap.add_argument("--rerank-timeout", type=float, default=config.RERANK_TIMEOUT_SECONDS)
    ap.add_argument("--json", help="write the full results here")
    ap.add_argument("--baseline", help="a saved --json file to compare with; exit 1 on a regression")
    ap.add_argument("--tolerance", type=float, default=0.02, help="allowed drop of the combined score (default 0.02)")
    args = ap.parse_args(argv)

    spec = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    slug = args.slug or spec["slug"]
    wanted = set(args.only or [])
    questions = [q for q in spec["questions"] if not wanted or q["id"] in wanted]
    rule_cases = [] if args.skip_rules else [c for c in spec.get("rule_cases", []) if not wanted or c["id"] in wanted]

    knowledge.KNOWLEDGE_CANDIDATES, knowledge.RERANK_MIN_SCORE = args.candidates, args.min_score
    rerank.RERANK_TIMEOUT_SECONDS = args.rerank_timeout
    cfg = {"slug": slug, "candidates": args.candidates, "min_score": args.min_score, "budget": args.budget,
           "rerank_timeout": args.rerank_timeout}
    try:
        repo = repos.get_repo(slug)
        if repo is None:
            raise AppError(f"Repo {slug} is not registered. Connect it in the app first.", 404)
        if not repo["indexed"]:
            raise AppError("The repo has no finished index yet.", 409)
        project_id = args.project_id or next(iter(repo["projects"]), None)
        if not project_id:
            raise AppError("No project is bound to this repo. Bind one (PUT /api/projects/{id}/binding) or pass --project-id.", 409)
        cfg["index_commit"] = repo["indexed"]["commit_sha"]
        print("Preparing the local models (first run downloads them)...")
        prepare_models(timeout=900)
        warnings = check_specs([q for q in questions], indexed_chunks(slug))
        defaults = {"doc_type": "BRD", "stage": "requirements", "tags": [], **spec.get("defaults", {})}
        ctx_args = {"project_id": project_id, "budget": args.budget, **defaults}
        rows = []
        for q in questions:
            print(f"  {q['id']} ...", end="\r", flush=True)
            rows.append(run_question(q, {**ctx_args, **{k: q[k] for k in ("doc_type", "stage", "tags") if k in q}}, cfg))
        rule_rows = [run_rule_case(c, project_id) for c in rule_cases]
    except AppError as exc:
        print(f"Cannot run: {exc.message}", file=sys.stderr)
        return 2

    summary = summarize(rows, rule_rows, cfg)
    report(rows, rule_rows, summary, cfg, warnings)
    result = {"config": cfg, "questions": rows, "rule_cases": rule_rows, "summary": summary, "spec_warnings": warnings}
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nSaved {args.json}")
    if args.baseline:
        bad = compare(json.loads(Path(args.baseline).read_text(encoding="utf-8")), rows, rule_rows, summary, args.tolerance)
        print("\nBaseline check: " + ("OK, no regressions" if not bad else "REGRESSIONS"))
        for line in bad:
            print(f"  - {line}")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
