"""Secret + PII redaction (§9). Runs BEFORE chunking, embedding and logging. Fails closed.

Rules run in order: specific secret formats, then generic ``key = "value"`` assignments, then the
entropy check for unknown token formats, then PII. Placeholders are typed (``[REDACTED:AWS_KEY]``)
and never change the line count, so citations (which point at line ranges) stay valid.

Still TODO(ingestion pod):
* Presidio / Azure AI Language PII detection (``uv sync --extra pii`` in rag-ingest). The built-in
  PII rules below cover emails, card numbers, US SSNs and IBANs only; names, phones and addresses
  need the NER-based detector.
* Per-tenant allowlists loaded from config (today: the module default only).
* Secret rules: a hand-ported subset of the gitleaks default ruleset. Keep ``.gitleaks.toml`` in
  CI as the backstop; the gitleaks binary is the source of truth for the full set.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from rag_core.interfaces import RedactionError, RedactionResult

Validator = Callable[[str], bool]

# Entropy check: quoted tokens that look random. Tuned on sample repos; see the tests for the cases.
ENTROPY_MIN_BITS = 4.2
ENTROPY_MIN_LENGTH = 20


@dataclass(frozen=True)
class Rule:
    """One detector. ``group`` redacts only that named group, keeping the surrounding key visible.
    ``validate`` must return True for a match to be redacted (checksums, entropy)."""

    kind: str
    pattern: re.Pattern[str]
    group: str | None = None
    validate: Validator | None = None


def shannon_bits_per_char(value: str) -> float:
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in Counter(value).values())


def _has_mixed_classes(value: str) -> bool:
    classes = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes >= 2


def _looks_random(value: str) -> bool:
    return (
        len(value) >= ENTROPY_MIN_LENGTH
        and _has_mixed_classes(value)
        and shannon_bits_per_char(value) >= ENTROPY_MIN_BITS
    )


def _luhn(value: str) -> bool:
    digits = re.sub(r"[ -]", "", value)
    if not (13 <= len(digits) <= 19 and digits.isdigit()):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_mod97(value: str) -> bool:
    iban = value.replace(" ", "")
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    try:
        return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1
    except ValueError:
        return False


DEFAULT_RULES: tuple[Rule, ...] = (
    # --- secrets: specific formats first ---------------------------------------------------
    Rule("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    Rule("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    Rule("GITLAB_TOKEN", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    Rule("SLACK_TOKEN", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    Rule(
        "SLACK_WEBHOOK",
        re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    ),
    Rule("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    Rule("STRIPE_KEY", re.compile(r"\b(?:sk|rk)_live_[0-9a-zA-Z]{24,}\b")),
    Rule("SENDGRID_KEY", re.compile(r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b")),
    Rule("NPM_TOKEN", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    Rule("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{32,}")),
    Rule("OPENAI_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    Rule(
        "JWT",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    Rule("AZURE_STORAGE_KEY", re.compile(r"AccountKey=[A-Za-z0-9+/=]{40,}")),
    # Patterns with a named ``secret`` group redact only that group, keeping the key visible.
    Rule(
        "CONNECTION_STRING_PASSWORD",
        re.compile(r"(?i)\bpassword=(?P<secret>[^;\s'\"]{4,})"),
        group="secret",
    ),
    Rule(
        "GENERIC_SECRET",
        re.compile(
            r"""(?ix)(?:secret|passwd|password|api[_-]?key|access[_-]?token|client[_-]?secret)
            ["']?\s*[:=]\s*["'](?!\[REDACTED:)(?P<secret>[^"'\s]{8,})["']"""
        ),
        group="secret",
    ),
    # --- secrets: unknown formats ----------------------------------------------------------
    Rule(
        "HIGH_ENTROPY",
        re.compile(r"""["'](?!\[REDACTED:)(?P<secret>[A-Za-z0-9+/=_\-]{20,})["']"""),
        group="secret",
        validate=_looks_random,
    ),
    # --- PII ---------------------------------------------------------------------------------
    Rule(
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),
    ),
    Rule("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), validate=_luhn),
    Rule("US_SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    Rule(
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"),
        validate=_iban_mod97,
    ),
)

# Values that must NOT be redacted even when a rule matches (fullmatch against the matched value).
# Test and documentation domains, and GitHub's no-reply addresses, are not personal data.
DEFAULT_ALLOW: tuple[re.Pattern[str], ...] = (
    re.compile(r"[^@\s]+@(?:[A-Za-z0-9-]+\.)*(?:example\.(?:com|org|net)|test|invalid|localhost)"),
    re.compile(r"[^@\s]+@users\.noreply\.github\.com"),
)

_PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PRIVATE_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def _apply(rule: Rule, line: str, counts: Counter[str], allow: tuple[re.Pattern[str], ...]) -> str:
    def repl(m: re.Match[str]) -> str:
        value = m.group(rule.group) if rule.group else m.group(0)
        if rule.validate is not None and not rule.validate(value):
            return m.group(0)
        if any(a.fullmatch(value) for a in allow):
            return m.group(0)
        counts[rule.kind] += 1
        placeholder = f"[REDACTED:{rule.kind}]"
        if rule.group is None:
            return placeholder
        s, e = m.span(rule.group)
        base = m.start()
        return m.group(0)[: s - base] + placeholder + m.group(0)[e - base :]

    return rule.pattern.sub(repl, line)


class EntitySpan(NamedTuple):
    start: int
    end: int
    kind: str


class EntityDetector(Protocol):
    """Model-based PII detector (for example Presidio NER). Called one line at a time so that line
    counts stay stable. Raising an exception makes the file fail closed."""

    def find(self, line: str) -> list[EntitySpan]: ...


def _apply_spans(
    spans: list[EntitySpan], line: str, counts: Counter[str], allow: tuple[re.Pattern[str], ...]
) -> str:
    # Keep the first of any overlapping spans, then replace right to left so offsets stay valid.
    kept: list[EntitySpan] = []
    for span in sorted(spans, key=lambda s: s.start):
        if kept and span.start < kept[-1].end:
            continue
        kept.append(span)
    for span in reversed(kept):
        value = line[span.start : span.end]
        if any(a.fullmatch(value) for a in allow):
            continue
        counts[span.kind] += 1
        line = f"{line[: span.start]}[REDACTED:{span.kind}]{line[span.end :]}"
    return line


@dataclass(frozen=True)
class RegexSecretRedactor:
    max_chars: int = 5_000_000
    rules: tuple[Rule, ...] = DEFAULT_RULES
    allow: tuple[re.Pattern[str], ...] = DEFAULT_ALLOW
    detectors: tuple[EntityDetector, ...] = ()

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
            for rule in self.rules:
                line = _apply(rule, line, counts, self.allow)
            for detector in self.detectors:
                line = _apply_spans(detector.find(line), line, counts, self.allow)
            lines[i] = line
        out = "\n".join(lines)
        if out.count("\n") != text.count("\n"):
            raise RedactionError("line count changed during redaction")
        return RedactionResult(text=out, counts={k: v for k, v in counts.items() if v})
