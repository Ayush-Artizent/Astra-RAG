"""NER PII. Tests that need Presidio skip unless the ``pii`` extra is installed."""

import pytest

from rag_core.redaction import RegexSecretRedactor
from rag_ingest.stages.redact import SourceAwareRedactor, build_redactor

CODE_LINE = "def get_user(user_id): return cache[user_id]\n"
PROSE = "Contact John Smith in London about the refund.\n"


def test_default_factory_is_regex_only() -> None:
    assert isinstance(build_redactor(), RegexSecretRedactor)
    assert build_redactor().detectors == ()


def test_ner_routes_prose_to_presidio_and_leaves_code_alone() -> None:
    pytest.importorskip("presidio_analyzer")
    r = build_redactor(ner=True)
    assert isinstance(r, SourceAwareRedactor)
    # NER on code flagged identifiers as LOCATION, so code must never reach it.
    assert r.redact("src/app.py", CODE_LINE).counts == {}
    out = r.redact("docs/brd.md", PROSE)
    assert "John Smith" not in out.text
    assert out.counts.get("PERSON", 0) >= 1


def test_ner_keeps_line_count() -> None:
    pytest.importorskip("presidio_analyzer")
    text = "# Notes\n\nJohn Smith called.\nNothing here.\n"
    out = build_redactor(ner=True).redact("notes.md", text)
    assert out.text.count("\n") == text.count("\n")


def test_missing_model_fails_at_startup() -> None:
    pytest.importorskip("presidio_analyzer")
    from rag_ingest.stages.presidio_pii import PresidioPiiDetector

    with pytest.raises(RuntimeError, match="not installed"):
        PresidioPiiDetector(model="en_core_web_does_not_exist")
