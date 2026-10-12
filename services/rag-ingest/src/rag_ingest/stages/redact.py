"""Redaction stage (§4.1 step 5).

The detector lives in rag_core so the API can redact query text with it too.
"""

from rag_core.redaction import RegexSecretRedactor

__all__ = ["RegexSecretRedactor"]
