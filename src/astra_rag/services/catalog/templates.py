"""Finds templates under `templates/` and reads their heading lists."""
from pathlib import PurePosixPath

from .models import TemplateVariant
from .sections import headings


def discover(entries: list[dict], list_dir) -> list[tuple[str, str | None, str]]:
    """Return (type_name, variant, path) for `templates/<type>.md` and `templates/<type>/<variant>.md`.

    `entries` is the listing of `templates/`; `list_dir(path)` lists a sub-folder.
    """
    found = []
    for e in sorted(entries, key=lambda x: x["name"]):
        name = e["name"]
        if e["type"] == "file" and name.lower().endswith(".md"):
            found.append((PurePosixPath(name).stem, None, f"templates/{name}"))
        elif e["type"] == "dir":
            for sub in sorted(list_dir(f"templates/{name}"), key=lambda x: x["name"]):
                if sub["type"] == "file" and sub["name"].lower().endswith(".md"):
                    found.append((name, PurePosixPath(sub["name"]).stem, f"templates/{name}/{sub['name']}"))
    return found


def template_headings(text: str) -> tuple[str, ...]:
    return tuple(title for _, title, _ in headings(text))


def with_defaults(variants: list[TemplateVariant]) -> None:
    """Mark the default per doc type when the manifest did not: a flat file, or the only variant, is the default."""
    by_type: dict[str, list[TemplateVariant]] = {}
    for v in variants:
        by_type.setdefault(v.doc_type, []).append(v)
    for group in by_type.values():
        if any(v.default for v in group):
            continue
        flat = [v for v in group if v.variant is None]
        if len(flat) == 1:
            flat[0].default = True
        elif len(group) == 1:
            group[0].default = True
