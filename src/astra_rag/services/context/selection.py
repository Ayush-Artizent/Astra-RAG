"""Filters a catalog by explicit doc type, stage and tags: `always` rules, then `applies_to` matches, then a template variant."""
from dataclasses import dataclass, field

from ..catalog.models import Catalog, RuleSection, Scope, TemplateVariant, Warning_
from ..catalog.sections import normalise
from ..errors import AppError


@dataclass(frozen=True)
class Request:
    doc_type: str
    stage: str | None = None
    tags: tuple[str, ...] = ()


@dataclass
class SelectedRule:
    rule: RuleSection
    matched_on: str  # "always", or "scope: doc_types, stages" naming the dimensions that matched


@dataclass
class Selection:
    doc_type: str  # the catalog's canonical name
    rules: list[SelectedRule]
    template: TemplateVariant | None
    warnings: list[Warning_] = field(default_factory=list)


def _lookup(catalog: Catalog) -> dict[str, str]:
    """Normalised doc type name or alias -> canonical name, for every type the catalog knows."""
    found: dict[str, str] = {}
    for name, aliases in catalog.doc_types.items():
        found[normalise(name)] = name
        for alias in aliases:
            found.setdefault(normalise(alias), name)
    for t in catalog.templates:
        found.setdefault(normalise(t.doc_type), t.doc_type)
    return found


def doc_type_names(catalog: Catalog) -> list[str]:
    """The canonical doc types a request may name."""
    return sorted(set(_lookup(catalog).values()))


def resolve_doc_type(catalog: Catalog, name: str) -> str:
    known = _lookup(catalog)
    canonical = known.get(normalise(name or ""))
    if canonical is None:
        options = ", ".join(sorted(set(known.values()))) or "none"
        raise AppError(f"Unknown document type {(name or '')[:60]!r}. Known types: {options}.", 422)
    return canonical


def _matched_dimensions(scope: Scope, doc_type: str, stage: str | None, tags: set[str], lookup: dict[str, str]) -> list[str] | None:
    """The dimensions a scope lists and the request satisfies, or None when any listed dimension is not satisfied."""
    matched = []
    if scope.doc_types:
        wanted = {normalise(lookup.get(normalise(d), d)) for d in scope.doc_types}
        if normalise(doc_type) not in wanted:
            return None
        matched.append("doc_types")
    if scope.stages:
        if stage is None or normalise(stage) not in {normalise(s) for s in scope.stages}:
            return None
        matched.append("stages")
    if scope.tags:
        if not tags & {normalise(t) for t in scope.tags}:
            return None
        matched.append("tags")
    return matched


def select_rules(catalog: Catalog, doc_type: str, stage: str | None, tags: set[str], lookup: dict[str, str]) -> list[SelectedRule]:
    always, scoped = [], []
    for rule in catalog.rules:
        if rule.selection == "always":
            always.append(SelectedRule(rule, "always"))
        elif rule.selection == "scope" and rule.scope:
            dims = _matched_dimensions(rule.scope, doc_type, stage, tags, lookup)
            if dims is not None:
                scoped.append(SelectedRule(rule, f"scope: {', '.join(dims)}"))

    def order(s: SelectedRule):
        return (s.rule.priority, s.rule.section.file, s.rule.section.start_line)

    return sorted(always, key=order) + sorted(scoped, key=order)


def select_template(catalog: Catalog, doc_type: str, stage: str | None, tags: set[str], lookup: dict[str, str],
                    warnings: list[Warning_]) -> TemplateVariant | None:
    """The scoped variant matching the most dimensions, otherwise the default variant."""
    group = [t for t in catalog.templates if t.doc_type == doc_type]
    if not group:
        warnings.append(Warning_("no_template", f"No template is defined for {doc_type}.", doc_type))
        return None
    best: tuple[int, int, TemplateVariant] | None = None
    for index, variant in enumerate(group):
        dims = _matched_dimensions(variant.scope, doc_type, stage, tags, lookup) if variant.scope else None
        if dims:
            rank = (-len(dims), 0 if variant.default else 1, index)
            if best is None or rank < best[:3]:
                best = (*rank, variant)
    if best is not None:
        return best[3]
    default = next((t for t in group if t.default), None)
    if default is None:
        warnings.append(Warning_("no_matching_template", f"No {doc_type} template matches this request and none is marked default.", doc_type))
    return default


def select(catalog: Catalog, request: Request) -> Selection:
    doc_type = resolve_doc_type(catalog, request.doc_type)
    lookup = _lookup(catalog)
    stage = (request.stage or "").strip() or None
    tags = {normalise(t) for t in request.tags if t and t.strip()}
    warnings: list[Warning_] = []

    unscoped = sum(1 for r in catalog.rules if r.selection == "relevance")
    if unscoped:
        warnings.append(Warning_(
            "unscoped_rules",
            f"{unscoped} rule section(s) have no scope and are never selected. Mark them `always: true` or give them `applies_to` in golden.yaml.",
            "golden.yaml"))
    rules = select_rules(catalog, doc_type, stage, tags, lookup)
    template = select_template(catalog, doc_type, stage, tags, lookup, warnings)
    return Selection(doc_type, rules, template, warnings)
