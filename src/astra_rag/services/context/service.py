"""Builds the preview response: the selected rules and the whole template for a project's request."""
from dataclasses import asdict

from ..catalog import service as catalog_service
from ..sources import adapter_for, parse_repo_url
from .selection import Request, select


def preview(project_id: str, doc_type: str, stage: str | None, tags: list[str]) -> dict:
    repo, catalog = catalog_service.catalog_for_project(project_id)
    chosen = select(catalog, Request(doc_type, stage, tuple(tags)))
    adapter = adapter_for(parse_repo_url(repo["url"]))  # citation links need no token

    def link(path: str, lines: tuple[int, int] | None = None) -> str:
        return adapter.citation_url(path, catalog.head_sha, lines)

    template = chosen.template
    return {
        "request": {"doc_type": chosen.doc_type, "stage": (stage or "").strip() or None, "tags": tags},
        "snapshot": {"rules_commit": catalog.head_sha},
        "rules": [{
            "file": s.rule.section.file, "section": s.rule.section.title, "text": s.rule.section.text,
            "matched_on": s.matched_on, "priority": s.rule.priority,
            "source_url": link(s.rule.section.file, (s.rule.section.start_line, s.rule.section.end_line)),
        } for s in chosen.rules],
        "template": None if template is None else {
            "path": template.path, "variant": template.variant, "text": template.text,
            "sections": list(template.headings), "source_url": link(template.path),
        },
        "warnings": [asdict(w) for w in [*catalog.warnings, *chosen.warnings]],
        "stale": catalog.stale,
    }
