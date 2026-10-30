"""Parses the optional `golden.yaml` (v1). Problems become warnings, never errors."""
import yaml

from .models import Manifest, Scope, Warning_

SUPPORTED_VERSION = 1
_SCOPE_KEYS = ("doc_types", "stages", "tags")


def parse_manifest(text: str | None) -> tuple[Manifest, list[Warning_]]:
    """Return the manifest and any warnings. `text=None` means the file is absent (not a warning)."""
    if text is None:
        return Manifest(), []
    warnings: list[Warning_] = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return Manifest(), [Warning_("manifest_invalid", "golden.yaml is not valid YAML; using conventions instead.", "golden.yaml")]
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return Manifest(), [Warning_("manifest_invalid", "golden.yaml must be a mapping at the top level; using conventions instead.", "golden.yaml")]

    version = data.get("version", SUPPORTED_VERSION)
    if version != SUPPORTED_VERSION:
        warnings.append(Warning_("manifest_version", f"golden.yaml version {version!r} is not supported (expected {SUPPORTED_VERSION}); reading it as v1.", "golden.yaml"))

    manifest = Manifest(present=True)
    manifest.doc_types = _doc_types(data.get("doc_types"), warnings)
    manifest.stages = tuple(_str_list(data.get("stages"), "stages", warnings))
    manifest.tags = tuple(_str_list(data.get("tags"), "tags", warnings))
    manifest.rules = _entries(data.get("rules"), "rules", warnings)
    manifest.templates = _entries(data.get("templates"), "templates", warnings)
    if isinstance(data.get("project_data"), dict):
        manifest.project_data = data["project_data"]
    return manifest, warnings


def read_scope(entry: dict, where: str, warnings: list[Warning_]) -> Scope | None:
    """Read an `applies_to` block. Returns None when absent or unusable."""
    raw = entry.get("applies_to")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        warnings.append(Warning_("manifest_invalid", "applies_to must be a mapping; ignored.", where))
        return None
    for key in raw:
        if key not in _SCOPE_KEYS:
            warnings.append(Warning_("manifest_unknown_key", f"Unknown applies_to key {key!r}; ignored.", where))
    values = {k: tuple(_str_list(raw.get(k), f"{where} applies_to.{k}", warnings)) for k in _SCOPE_KEYS}
    return Scope(**values) if any(values.values()) else None


def _doc_types(raw, warnings: list[Warning_]) -> dict[str, tuple[str, ...]]:
    """Accepts a list of names, or a mapping name -> {aliases: [...]} (or a bare alias list)."""
    result: dict[str, tuple[str, ...]] = {}
    if raw is None:
        return result
    if isinstance(raw, list):
        return {str(name): () for name in raw if isinstance(name, (str, int))}
    if not isinstance(raw, dict):
        warnings.append(Warning_("manifest_invalid", "doc_types must be a list or a mapping; ignored.", "golden.yaml doc_types"))
        return result
    for name, body in raw.items():
        aliases = body.get("aliases") if isinstance(body, dict) else body
        result[str(name)] = tuple(_str_list(aliases, f"doc_types.{name}", warnings))
    return result


def _str_list(raw, where: str, warnings: list[Warning_]) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, int)):
        raw = [raw]
    if not isinstance(raw, list):
        warnings.append(Warning_("manifest_invalid", f"{where} must be a list; ignored.", "golden.yaml"))
        return []
    return [str(v).strip() for v in raw if isinstance(v, (str, int)) and str(v).strip()]


def _entries(raw, key: str, warnings: list[Warning_]) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        warnings.append(Warning_("manifest_invalid", f"{key} must be a list; ignored.", f"golden.yaml {key}"))
        return []
    good = []
    for i, entry in enumerate(raw):
        if isinstance(entry, dict):
            good.append(entry)
        else:
            warnings.append(Warning_("manifest_invalid", f"{key}[{i}] must be a mapping; skipped.", f"golden.yaml {key}[{i}]"))
    return good
