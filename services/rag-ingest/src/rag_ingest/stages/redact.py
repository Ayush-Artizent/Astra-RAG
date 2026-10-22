"""Redaction stage (§4.1 step 5).

The detector lives in rag_core so the API can redact query text with it too. Ingest code imports
from here, so the stage's public surface is the same whichever package owns the implementation.
Redaction runs before chunking, embedding and logging. A RedactionError means the file is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from rag_core.interfaces import RedactionError, RedactionResult, Redactor
from rag_core.redaction import DEFAULT_ALLOW, DEFAULT_RULES, RegexSecretRedactor, Rule
from rag_ingest.stages.presidio_pii import PresidioPiiDetector

# NER (names, phones, locations) only runs on prose. On code it flags identifiers like
# ``cache[user_id]`` as LOCATION: 500+ false hits across this repo. Code keeps regex + entropy.
PROSE_SUFFIXES = frozenset({".md", ".rst", ".txt", ".adoc"})


@dataclass(frozen=True)
class SourceAwareRedactor:
    code: Redactor
    prose: Redactor

    def redact(self, path: str, text: str) -> RedactionResult:
        is_prose = PurePosixPath(path).suffix.lower() in PROSE_SUFFIXES
        return (self.prose if is_prose else self.code).redact(path, text)


def build_redactor(*, ner: bool = False) -> Redactor:
    """Secrets + regex PII always. ``ner=True`` adds Presidio names, phones and locations to prose.

    Raises RuntimeError at construction if ``ner`` is requested but the ``pii`` extra or its
    spaCy model is missing, so the worker never starts without the checks it was configured for.
    """
    code = RegexSecretRedactor()
    if not ner:
        return code
    prose = RegexSecretRedactor(detectors=(PresidioPiiDetector(),))
    return SourceAwareRedactor(code=code, prose=prose)


__all__ = [
    "DEFAULT_ALLOW",
    "DEFAULT_RULES",
    "PROSE_SUFFIXES",
    "PresidioPiiDetector",
    "RedactionError",
    "RedactionResult",
    "RegexSecretRedactor",
    "Rule",
    "SourceAwareRedactor",
    "build_redactor",
]
