"""Language / doc-type detection by path. Extend per tenant via config overrides."""

from __future__ import annotations

from pathlib import PurePosixPath

from rag_core.schemas import DocType

_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".scala": "scala",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".sql": "sql",
    ".md": "markdown",
    ".markdown": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".proto": "proto",
    ".tf": "hcl",
    ".bicep": "bicep",
}

_TEST_MARKERS = ("/test/", "/tests/", "/__tests__/", "/spec/")


def detect_language(path: str) -> str | None:
    return _EXT_LANG.get(PurePosixPath(path).suffix.lower())


def is_test_path(path: str) -> bool:
    p = "/" + path.lower()
    name = PurePosixPath(p).name
    return (
        any(m in p for m in _TEST_MARKERS)
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith(("_test.go", "tests.cs", "test.java"))
    )


def detect_doc_type(path: str, *, golden: bool = False) -> DocType:
    p = path.lower()
    lang = detect_language(path)
    if is_test_path(path):
        return DocType.TEST
    if lang == "markdown":
        name = PurePosixPath(p).name
        if name.startswith("readme"):
            return DocType.README
        if "/adr/" in p or "/adrs/" in p or name.startswith("adr-"):
            return DocType.ADR
        if "brd" in p:
            return DocType.BRD
        if "standard" in p or "guideline" in p:
            return DocType.STANDARD
        return DocType.SPEC if golden else DocType.README
    if lang in {"yaml", "json", "toml", "xml", "hcl", "bicep", "proto"}:
        return DocType.CONFIG
    return DocType.CODE
