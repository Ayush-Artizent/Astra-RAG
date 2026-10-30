"""Builds the catalog of rules and templates from a reader (live host reads, or a local clone)."""
import threading
from dataclasses import replace
from typing import Protocol

from ..errors import AppError
from ..validator import find_missing
from ...config import (
    DEFAULT_RULE_PRIORITY, GOLDEN_MANIFEST_NAME, MAX_CATALOG_FILE_BYTES, RULE_FILES, RULES_FOLDER,
    TEMPLATES_FOLDER,
)
from .manifest import parse_manifest, read_scope
from .models import Catalog, Manifest, RuleSection, Scope, TemplateVariant, Warning_
from .sections import matches_heading, normalise, split_sections
from .templates import discover, template_headings, with_defaults


class SourceReader(Protocol):
    """What the catalog needs from a repo. P2's source adapter will provide this against the host."""

    def head_sha(self) -> str: ...
    def list_dir(self, path: str) -> list[dict]:
        """Entries as {'name', 'type': 'file'|'dir'} plus an optional blob 'sha'. '' is the repo root."""
    def read_file(self, path: str) -> str | None:
        """File text, or None when the file does not exist."""


class _Reads:
    """Memoised listings and file bodies; bodies are cached by blob sha across builds when the reader gives one."""

    def __init__(self, reader: SourceReader, bodies: dict):
        self.reader, self.bodies, self._dirs = reader, bodies, {}

    def listing(self, path: str) -> list[dict]:
        if path not in self._dirs:
            self._dirs[path] = self.reader.list_dir(path)
        return self._dirs[path]

    def read(self, path: str) -> str | None:
        parent, _, name = path.rpartition("/")
        sha = next((e.get("sha") for e in self.listing(parent) if e["name"] == name), None)
        if sha and (path, sha) in self.bodies:
            return self.bodies[(path, sha)]
        text = self.reader.read_file(path)
        if text is not None and sha:
            self.bodies[(path, sha)] = text
        return text


def build_catalog(reader: SourceReader, bodies: dict | None = None) -> Catalog:
    reads = _Reads(reader, bodies if bodies is not None else {})
    warnings: list[Warning_] = []
    root = reads.listing("")

    manifest_text = reads.read(GOLDEN_MANIFEST_NAME) if any(
        e["name"] == GOLDEN_MANIFEST_NAME and e["type"] == "file" for e in root) else None
    manifest, found = parse_manifest(manifest_text)
    warnings += found

    for missing in find_missing(root):
        warnings.append(Warning_("required_missing", f"Required item {missing} is missing from the repo root.", missing))

    rules = _rules(reads, root, manifest, warnings)
    templates = _templates(reads, root, manifest, warnings)

    declared = manifest.doc_types or {t.doc_type: () for t in templates}
    if not any(r.always for r in rules):
        warnings.append(Warning_("no_always_rules", "No always-on rules are defined, so no rule is guaranteed to apply. Mark must-apply sections `always: true` in golden.yaml.", GOLDEN_MANIFEST_NAME))
    return Catalog(reader.head_sha(), declared, manifest.stages, manifest.tags, rules, templates, warnings, manifest.present)


def _rule_files(reads: _Reads, root: list[dict]) -> list[str]:
    files = [n for n in RULE_FILES if any(e["name"] == n and e["type"] == "file" for e in root)]
    if any(e["name"] == RULES_FOLDER and e["type"] == "dir" for e in root):
        files += _walk_md(reads, RULES_FOLDER)
    return files


def _walk_md(reads: _Reads, folder: str) -> list[str]:
    found = []
    for e in sorted(reads.listing(folder), key=lambda x: x["name"]):
        path = f"{folder}/{e['name']}"
        if e["type"] == "dir":
            found += _walk_md(reads, path)
        elif e["name"].lower().endswith(".md"):
            found.append(path)
    return found


def _rules(reads: _Reads, root: list[dict], manifest: Manifest, warnings: list[Warning_]) -> list[RuleSection]:
    rules: list[RuleSection] = []
    for file in _rule_files(reads, root):
        text = reads.read(file)
        if text is None:
            warnings.append(Warning_("rule_file_missing", f"{file} could not be read.", file))
            continue
        if len(text.encode("utf-8")) > MAX_CATALOG_FILE_BYTES:
            warnings.append(Warning_("rule_file_too_large", f"{file} is too large to catalog; skipped.", file))
            continue
        rules += [RuleSection(s) for s in split_sections(file, text)]
    for file in (n for n in RULE_FILES if not any(r.section.file == n for r in rules)):
        warnings.append(Warning_("rule_file_empty", f"{file} has no rule sections.", file))

    known_types = {normalise(k) for k in manifest.doc_types}
    for i, entry in enumerate(manifest.rules):
        _apply_rule_entry(entry, i, rules, known_types, warnings)
    return rules


def _apply_rule_entry(entry: dict, index: int, rules: list[RuleSection], known_types: set[str], warnings: list[Warning_]) -> None:
    where = f"golden.yaml rules[{index}]"
    file, section = entry.get("file"), entry.get("section")
    if not isinstance(file, str) or not file:
        warnings.append(Warning_("manifest_invalid", "A rule entry needs a `file`; skipped.", where))
        return
    in_file = [r for r in rules if r.section.file == file]
    if not in_file:
        warnings.append(Warning_("rule_file_missing", f"{file} is not a readable rule file; entry skipped.", where))
        return
    targets = in_file if section is None else [r for r in in_file if matches_heading(r.section, str(section))]
    if not targets:
        warnings.append(Warning_("rule_section_missing", f"No section {section!r} in {file}; entry skipped.", where))
        return

    always = entry.get("always") is True
    scope = read_scope(entry, where, warnings)
    if not always and scope is None:
        warnings.append(Warning_("rule_no_scope", "Entry has neither `always: true` nor `applies_to`; it is chosen by relevance like any unlisted section.", where))
        return
    if scope and known_types:
        for name in scope.doc_types:
            if normalise(name) not in known_types:
                warnings.append(Warning_("unknown_doc_type", f"Doc type {name!r} is not declared under doc_types.", where))
    priority = entry.get("priority", DEFAULT_RULE_PRIORITY)
    if not isinstance(priority, int) or isinstance(priority, bool):
        warnings.append(Warning_("manifest_invalid", "priority must be a whole number; using the default.", where))
        priority = DEFAULT_RULE_PRIORITY
    for r in targets:
        _merge(r, always, scope, priority)


def _merge(rule: RuleSection, always: bool, scope: Scope | None, priority: int) -> None:
    """Several entries can hit one section: `always` wins, otherwise the lowest priority number."""
    if rule.selection == "always":
        return
    if always:
        rule.always, rule.selection, rule.priority, rule.scope = True, "always", priority, None
    elif rule.selection == "relevance" or priority < rule.priority:
        rule.selection, rule.priority, rule.scope = "scope", priority, scope


def _canonical_type(name: str, manifest: Manifest) -> tuple[str, bool]:
    """Map a template/doc-type name to the manifest's name (by name or alias). Returns (name, known)."""
    key = normalise(name)
    for canon, aliases in manifest.doc_types.items():
        if key == normalise(canon) or key in (normalise(a) for a in aliases):
            return canon, True
    return name.upper(), not manifest.doc_types


def _templates(reads: _Reads, root: list[dict], manifest: Manifest, warnings: list[Warning_]) -> list[TemplateVariant]:
    if not any(e["name"] == TEMPLATES_FOLDER and e["type"] == "dir" for e in root):
        return []
    found = discover(reads.listing(TEMPLATES_FOLDER), reads.listing)
    variants: list[TemplateVariant] = []
    for name, variant, path in found:
        text = reads.read(path)
        if text is None or len(text.encode("utf-8")) > MAX_CATALOG_FILE_BYTES:
            warnings.append(Warning_("template_unreadable", f"{path} could not be read; skipped.", path))
            continue
        doc_type, known = _canonical_type(name, manifest)
        if not known:
            warnings.append(Warning_("unknown_doc_type", f"Template type {name!r} is not declared under doc_types.", path))
        variants.append(TemplateVariant(doc_type, variant, path, template_headings(text), text=text))
    if not variants:
        warnings.append(Warning_("no_templates", "templates/ contains no markdown templates.", TEMPLATES_FOLDER))

    for i, entry in enumerate(manifest.templates):
        _apply_template_entry(entry, i, variants, manifest, warnings)
    with_defaults(variants)

    by_type: dict[str, list[TemplateVariant]] = {}
    for v in variants:
        by_type.setdefault(v.doc_type, []).append(v)
    for doc_type, group in by_type.items():
        if not any(v.default for v in group):
            warnings.append(Warning_("no_default_variant", f"Template type {doc_type} has several variants and none is marked `default: true`.", doc_type))
    return variants


def _apply_template_entry(entry: dict, index: int, variants: list[TemplateVariant], manifest: Manifest, warnings: list[Warning_]) -> None:
    where = f"golden.yaml templates[{index}]"
    file, name, variant = entry.get("file"), entry.get("type"), entry.get("variant")
    if file:
        match = [v for v in variants if v.path == file]
    elif name:
        canon, _ = _canonical_type(str(name), manifest)
        match = [v for v in variants if v.doc_type == canon and normalise(v.variant or "") == normalise(str(variant or ""))]
    else:
        warnings.append(Warning_("manifest_invalid", "A template entry needs `type` or `file`; skipped.", where))
        return
    if not match:
        warnings.append(Warning_("template_missing", "No template file matches this entry; skipped.", where))
        return
    scope = read_scope(entry, where, warnings)
    for v in match:
        v.scope = scope
        v.default = entry.get("default") is True


MAX_CACHED_BODIES = 500


class CatalogCache:
    """Builds a catalog only when the head sha changed; keeps file bodies by blob sha between builds.

    If the host cannot be reached and an earlier catalog exists, that one is returned marked `stale`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._catalogs: dict[str, Catalog] = {}
        self._bodies: dict = {}

    def get(self, key: str, reader: SourceReader) -> Catalog:
        with self._lock:
            cached = self._catalogs.get(key)
            try:
                sha = reader.head_sha()
                if cached and cached.head_sha == sha:
                    return cached
                if len(self._bodies) > MAX_CACHED_BODIES:
                    self._bodies.clear()
                catalog = build_catalog(reader, self._bodies)
            except (AppError, OSError) as exc:
                if cached is None:
                    if isinstance(exc, AppError):
                        raise
                    raise AppError("The repository could not be read to build the catalog.", 502) from None
                return replace(cached, stale=True)
            self._catalogs[key] = catalog
            return catalog
