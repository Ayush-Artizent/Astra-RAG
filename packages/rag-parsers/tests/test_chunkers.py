from rag_core.schemas import DocType
from rag_parsers import SourceFile, default_registry
from rag_parsers.chunkers.markdown import MarkdownChunker
from rag_parsers.chunkers.window import WindowChunker
from rag_parsers.detect import detect_doc_type, detect_language

MD = """# Payments
intro
## Refunds
### Eligibility
rules here
```python
# not a heading
x = 1
```
## Chargebacks
text
"""


def test_markdown_heading_paths_and_fences() -> None:
    chunks = MarkdownChunker().chunk(SourceFile("docs/p.md", MD, "markdown", DocType.SPEC))
    paths = [c.heading_path for c in chunks]
    assert ["Payments", "Refunds", "Eligibility"] in paths
    assert ["Payments", "Chargebacks"] in paths
    elig = next(c for c in chunks if c.heading_path == ["Payments", "Refunds", "Eligibility"])
    assert "# not a heading" in elig.text  # fence kept intact, not split


def test_window_chunker_covers_every_line() -> None:
    text = "\n".join(f"line {i}" for i in range(1, 251))
    chunks = WindowChunker(target_lines=50, max_lines=80, overlap=5).chunk(
        SourceFile("x.cobol", text, None, DocType.CODE)
    )
    covered = set()
    for c in chunks:
        covered |= set(range(c.start_line, c.end_line + 1))
    assert covered == set(range(1, 251))


def test_registry_falls_back_for_unknown_language() -> None:
    reg = default_registry()
    assert reg.resolve("a.md", "markdown").name == "markdown"
    assert reg.resolve("a.xyz", None).name == "window"


def test_detection() -> None:
    assert detect_language("src/a.ts") == "typescript"
    assert detect_doc_type("tests/test_a.py") is DocType.TEST
    assert detect_doc_type("docs/adr/0001-x.md") is DocType.ADR
    assert detect_doc_type("brds/payments-brd.md", golden=True) is DocType.BRD
