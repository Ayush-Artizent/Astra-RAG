"""Builds the context responses: the selected rules and template (preview), plus knowledge and a budget (get_context)."""
from dataclasses import asdict

from ...config import CONTEXT_BUDGET_RANGE, CONTEXT_BUDGET_TOKENS
from ..catalog import service as catalog_service
from ..catalog.models import Warning_
from ..errors import AppError
from ..sources import adapter_for, parse_repo_url
from . import knowledge
from .budget import Budget
from .rerank import Reranker
from .selection import Request, Selection, select


def _shape(repo: dict, catalog, chosen: Selection, stage: str | None, tags: list[str]) -> dict:
    adapter = adapter_for(parse_repo_url(repo["url"]))  # citation links need no token

    def link(path: str, lines: tuple[int, int] | None = None) -> str:
        return adapter.citation_url(path, catalog.head_sha, lines)

    template = chosen.template
    return {
        "request": {"doc_type": chosen.doc_type, "stage": (stage or "").strip() or None, "tags": tags},
        "rules": [{
            "file": s.rule.section.file, "section": s.rule.section.title, "text": s.rule.section.text,
            "matched_on": s.matched_on, "priority": s.rule.priority,
            "source_url": link(s.rule.section.file, (s.rule.section.start_line, s.rule.section.end_line)),
        } for s in chosen.rules],
        "template": None if template is None else {
            "path": template.path, "variant": template.variant, "text": template.text,
            "sections": list(template.headings), "source_url": link(template.path),
        },
        "warnings": [*catalog.warnings, *chosen.warnings],
        "stale": catalog.stale,
    }


def preview(project_id: str, doc_type: str, stage: str | None, tags: list[str]) -> dict:
    repo, catalog = catalog_service.catalog_for_project(project_id)
    chosen = select(catalog, Request(doc_type, stage, tuple(tags)))
    shaped = _shape(repo, catalog, chosen, stage, tags)
    return {
        "request": shaped["request"], "snapshot": {"rules_commit": catalog.head_sha},
        "rules": shaped["rules"], "template": shaped["template"],
        "warnings": [asdict(w) for w in shaped["warnings"]], "stale": shaped["stale"],
    }


def get_context(project_id: str, doc_type: str, text: str, stage: str | None = None, tags: list[str] | None = None,
                budget: int | None = None, reranker: Reranker | None = None) -> dict:
    """Rules, whole template and knowledge for one request, within a token budget (see budget.py for the order)."""
    tags = tags or []
    if not text.strip():
        raise AppError("The request text is required: it is what the project data is searched with.", 422)
    low, high = CONTEXT_BUDGET_RANGE
    if budget is not None and not low <= budget <= high:
        raise AppError(f"The budget must be between {low} and {high} tokens.", 422)
    repo, catalog = catalog_service.catalog_for_project(project_id)
    chosen = select(catalog, Request(doc_type, stage, tuple(tags)))
    shaped = _shape(repo, catalog, chosen, stage, tags)

    spend = Budget(budget or CONTEXT_BUDGET_TOKENS)
    always = [r for r in shaped["rules"] if r["matched_on"] == "always"]
    scoped = [r for r in shaped["rules"] if r["matched_on"] != "always"]
    rules = spend.take_items(always, "always_rules", lambda r: r["text"])
    template = shaped["template"]
    if template is not None:
        fitted = spend.take_text(template["text"], "template")
        template = {**template, "text": fitted, "truncated": fitted != template["text"]}
    rules += spend.take_items(scoped, "scope_rules", lambda r: r["text"])

    found = knowledge.retrieve(repo["slug"], text, reranker=reranker)
    items = spend.take_items(found.items, "knowledge", lambda i: i["text"])

    warnings = shaped["warnings"]
    if spend.truncated:
        warnings.append(Warning_("budget_truncated", "Over the token budget, so content was left out: "
                                 + ", ".join(spend.truncated) + ". Ask for a larger budget.", "budget"))
    indexed = repo.get("indexed")
    return {
        "request": shaped["request"],
        "snapshot": {"rules_commit": catalog.head_sha, "index_commit": indexed["commit_sha"] if indexed else None},
        "rules": rules, "template": template,
        "knowledge": {"items": items, "total_count": len(found.items), "truncated": len(items) < len(found.items)},
        "budget": {"limit": spend.limit, "used": spend.used, "truncated": spend.truncated},
        "status": {"rules": "stale" if catalog.stale else "ok", "knowledge": found.status, "rerank": found.rerank},
        "warnings": [asdict(w) for w in warnings], "stale": catalog.stale,
    }
