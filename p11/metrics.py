"""P11 metric functions: pure, no I/O, no models. `run_eval.py` feeds them what the pipeline returned.

A chunk is a dict with `file`, `heading_path` (list) and `text`. A source spec is `{file, heading?, row?}`:
`file` matches the path exactly or as a trailing path part, `heading` equals one heading segment (case-insensitive,
leading numbering ignored), `row` must appear in the chunk text (CSV row chunks repeat their id).
"""
import re

W_EVIDENCE, W_RULES, W_HEALTH = 0.6, 0.3, 0.1  # combined score weights


def norm(text: str) -> str:
    """Lower-case with spaces and thousands commas removed, so '10,000' finds '10000' and '2.5 s' finds '2.5s'."""
    return re.sub(r"[\s,]+", "", str(text).lower())  # str(): YAML turns 2026-11-15 into a date


def _segment(text: str) -> str:
    return re.sub(r"^\d+[.)]?\s*", "", text.strip()).lower()


def source_matches(spec: dict, chunk: dict) -> bool:
    path = (chunk.get("file") or "").replace("\\", "/")
    want = spec["file"].replace("\\", "/")
    if path != want and not path.endswith("/" + want):
        return False
    if spec.get("heading") and _segment(spec["heading"]) not in [_segment(h) for h in chunk.get("heading_path") or []]:
        return False
    return not spec.get("row") or spec["row"].lower() in (chunk.get("text") or "").lower()


def source_ranks(specs: list[dict], chunks: list[dict]) -> list[int | None]:
    """For each spec, the 1-based rank of the first chunk that matches it, or None."""
    return [next((i for i, c in enumerate(chunks, 1) if source_matches(s, c)), None) for s in specs]


def recall_at(ranks: list[int | None], mode: str, k: int | None) -> float | None:
    """`all`: share of the sources found within k. `any`: 1 if one of them is. k=None means the whole list."""
    if not ranks:
        return None
    hits = [r is not None and (k is None or r <= k) for r in ranks]
    return float(any(hits)) if mode == "any" else sum(hits) / len(hits)


def reciprocal_rank(ranks: list[int | None]) -> float | None:
    """1 / rank of the best-placed expected source (0 when none is found)."""
    if not ranks:
        return None
    found = [r for r in ranks if r is not None]
    return 1 / min(found) if found else 0.0


def dropped_relevant(before: list[int | None], after: list[int | None]) -> tuple[int, int]:
    """(expected sources that were in the list before a cut but not after, expected sources that were in it before)."""
    present = [(b, a) for b, a in zip(before, after) if b is not None]
    return sum(1 for _, a in present if a is None), len(present)


def fact_recall(facts: list[str], chunks: list[dict]) -> float | None:
    if not facts:
        return None
    blob = norm(" ".join(c.get("text") or "" for c in chunks))
    return sum(norm(f) in blob for f in facts) / len(facts)


def evidence_score(question: dict, source_recall: float | None, facts: float | None, answered: bool) -> float:
    """What one question earns for the evidence the caller finally gets. A no-answer question earns 1 for returning nothing."""
    if question.get("negative"):
        return 0.0 if answered else 1.0
    parts = [p for p in (source_recall, facts) if p is not None]
    return sum(parts) / len(parts) if parts else 0.0


def rule_matches(token: str, rule: dict) -> bool:
    """`FILE#N` = a rule in that file whose heading starts with N; any other token must appear in the heading or first line."""
    if "#" in token:
        file, number = token.split("#", 1)
        path = (rule.get("file") or "").replace("\\", "/")
        return (path == file or path.endswith("/" + file)) and bool(
            re.match(rf"^\W*(?:section\s+)?{re.escape(number)}(?!\d)", rule.get("section") or "", re.I))
    first_line = (rule.get("text") or "").strip().splitlines()[:1]
    return token.lower() in " ".join([rule.get("section") or "", *first_line]).lower()


def rule_scores(expected: list[str], selected: list[dict]) -> dict:
    """Precision, recall and F1 of the scope-selected rules against the expected tokens, plus what was missed or unexpected."""
    found = [t for t in expected if any(rule_matches(t, r) for r in selected)]
    useful = [r for r in selected if any(rule_matches(t, r) for t in expected)]
    precision = len(useful) / len(selected) if selected else (1.0 if not expected else 0.0)
    recall = len(found) / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1,
            "missing": [t for t in expected if t not in found],
            "unexpected": [f"{r.get('file')}#{r.get('section')}" for r in selected if r not in useful]}


def template_ok(expected: str | None, template: dict | None) -> bool | None:
    if not expected:
        return None
    return bool(template) and expected in f"{template.get('variant')} {template.get('path')}"


def combined(evidence: float | None, rules: float | None, degraded_rate: float | None) -> float | None:
    """0.6 evidence + 0.3 rules + 0.1 health (1 - degraded rate); a part with no data is left out and the rest rescaled."""
    parts = [(W_EVIDENCE, evidence), (W_RULES, rules), (W_HEALTH, None if degraded_rate is None else 1 - degraded_rate)]
    live = [(w, v) for w, v in parts if v is not None]
    return sum(w * v for w, v in live) / sum(w for w, _ in live) if live else None


def mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None
