"""Data shapes for the golden catalog (rules, templates, warnings)."""
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Warning_:
    """A problem found while building the catalog. Never fatal: the item falls back to conventions."""
    code: str
    message: str
    where: str = ""


@dataclass(frozen=True)
class Scope:
    """Where a rule or template variant applies. An empty list means 'any'."""
    doc_types: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass
class Section:
    """One heading section of a markdown file (a single rule when the file is a rule file)."""
    id: str
    file: str
    title: str
    heading_path: tuple[str, ...]
    level: int
    start_line: int
    end_line: int
    text: str


@dataclass
class RuleSection:
    section: Section
    always: bool = False
    scope: Scope | None = None
    priority: int = 100
    selection: str = "relevance"  # always | scope | relevance


@dataclass
class TemplateVariant:
    doc_type: str
    variant: str | None
    path: str
    headings: tuple[str, ...]
    scope: Scope | None = None
    default: bool = False


@dataclass
class Manifest:
    """Parsed `golden.yaml`. Every field has a safe default so a missing or broken file still works."""
    doc_types: dict[str, tuple[str, ...]] = field(default_factory=dict)  # canonical name -> aliases
    stages: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    rules: list[dict] = field(default_factory=list)
    templates: list[dict] = field(default_factory=list)
    project_data: dict = field(default_factory=dict)
    present: bool = False


@dataclass
class Catalog:
    head_sha: str
    doc_types: dict[str, tuple[str, ...]]
    stages: tuple[str, ...]
    tags: tuple[str, ...]
    rules: list[RuleSection]
    templates: list[TemplateVariant]
    warnings: list[Warning_]
    manifest_present: bool
    stale: bool = False  # the host could not be reached, so this is the last good catalog

    def to_dict(self, include_text: bool = False) -> dict:
        """JSON-ready view for the catalog endpoint. Rule text is left out unless asked for."""
        rules = []
        for r in self.rules:
            s = r.section
            item = {
                "id": s.id, "file": s.file, "section": s.title, "heading_path": list(s.heading_path),
                "selection": r.selection, "always": r.always, "priority": r.priority,
                "scope": asdict(r.scope) if r.scope else None,
            }
            if include_text:
                item["text"] = s.text
            rules.append(item)
        return {
            "head_sha": self.head_sha,
            "manifest_present": self.manifest_present,
            "stale": self.stale,
            "doc_types": {k: list(v) for k, v in self.doc_types.items()},
            "stages": list(self.stages),
            "tags": list(self.tags),
            "rules": rules,
            "templates": [
                {"doc_type": t.doc_type, "variant": t.variant, "path": t.path, "default": t.default,
                 "headings": list(t.headings), "scope": asdict(t.scope) if t.scope else None}
                for t in self.templates
            ],
            "warnings": [asdict(w) for w in self.warnings],
        }
