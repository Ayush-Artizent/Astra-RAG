"""Identifier-aware tokenization (§6.1): "code search lives or dies on exact identifiers".

Splits camelCase, PascalCase, snake_case, kebab-case and dotted paths into sub-tokens while
keeping the original token. This is the reference behaviour the Azure AI Search custom
analyzer must match; the eval set will catch drift.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9_.$-]+")
_SPLIT = re.compile(r"[_.$-]+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def tokenize_identifiers(text: str) -> list[str]:
    out: list[str] = []
    for raw in _WORD.findall(text):
        token = raw.strip("._-$")
        if not token:
            continue
        lowered = token.lower()
        out.append(lowered)
        parts = [p for piece in _SPLIT.split(token) for p in _CAMEL.findall(piece)]
        if len(parts) > 1 or (parts and parts[0].lower() != lowered):
            out.extend(p.lower() for p in parts)
    return out
