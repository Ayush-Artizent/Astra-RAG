"""Secret + PII redaction (§9). Runs BEFORE chunking, embedding and logging. Fails closed.

The regex detector below is the MVP baseline for secrets. TODO(ingestion pod):
* entropy checks for unknown token formats,
* PII via Presidio / Azure AI Language (``uv sync --extra pii``), tuned against real repos,
* per-tenant allowlists for known false positives.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from rag_core.interfaces import RedactionError, RedactionResult

# Single-line patterns only; multi-line blocks are handled separately to keep line counts stable.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS_KEY": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "GITLAB_TOKEN": re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "AZURE_STORAGE_KEY": re.compile(r"AccountKey=[A-Za-z0-9+/=]{40,}"),
    # Patterns with a named ``secret`` group redact only that group, keeping the key visible.
    "CONNECTION_STRING_PASSWORD": re.compile(r"(?i)\bpassword=(?P<secret>[^;\s'\"]{4,})"),
    "GENERIC_SECRET": re.compile(
        r"""(?ix)(?:secret|passwd|password|api[_-]?key|access[_-]?token|client[_-]?secret)
        ["']?\s*[:=]\s*["'](?!\[REDACTED:)(?P<secret>[^"'\s]{8,})["']"""
    ),
}

_PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PRIVATE_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def _replacer(kind: str) -> Callable[[re.Match[str]], str]:
    placeholder = f"[REDACTED:{kind}]"

    def repl(m: re.Match[str]) -> str:
        if "secret" not in m.re.groupindex:
            return placeholder
        s, e = m.span("secret")
        base = m.start()
        return m.group(0)[: s - base] + placeholder + m.group(0)[e - base :]

    return repl


@dataclass(frozen=True)
class RegexSecretRedactor:
    max_chars: int = 5_000_000

    def redact(self, path: str, text: str) -> RedactionResult:
        if len(text) > self.max_chars:
            raise RedactionError(f"file too large to scan safely: {path}")
        try:
            return self._redact(text)
        except Exception as exc:  # fail closed on ANY detector error
            raise RedactionError(f"redaction failed for {path}") from exc

    def _redact(self, text: str) -> RedactionResult:
        counts: Counter[str] = Counter()
        lines = text.split("\n")
        in_key = False
        for i, line in enumerate(lines):
            if in_key or _PRIVATE_KEY_BEGIN.search(line):
                if not in_key:
                    counts["PRIVATE_KEY"] += 1
                in_key = not _PRIVATE_KEY_END.search(line)
                lines[i] = "[REDACTED:PRIVATE_KEY]"
                continue
            for kind, pattern in SECRET_PATTERNS.items():
                line, n = pattern.subn(_replacer(kind), line)
                counts[kind] += n
            lines[i] = line
        out = "\n".join(lines)
        if out.count("\n") != text.count("\n"):
            raise RedactionError("line count changed during redaction")
        return RedactionResult(text=out, counts={k: v for k, v in counts.items() if v})
