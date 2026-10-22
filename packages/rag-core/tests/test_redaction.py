"""Redaction coverage. Sample values are fake (AWS docs examples, Luhn/mod-97 test vectors)."""

from __future__ import annotations

import re

import pytest

from rag_core.interfaces import RedactionError
from rag_core.redaction import DEFAULT_RULES, RegexSecretRedactor, Rule, _looks_random

# (kind, line, value that must not survive redaction)
SECRET_SAMPLES = [
    ("AWS_KEY", 'AWS_ACCESS = "AKIAIOSFODNN7EXAMPLE"', "AKIAIOSFODNN7EXAMPLE"),
    ("GITHUB_TOKEN", "token = ghp_" + "a1B2" * 9, "ghp_a1B2"),
    ("GITLAB_TOKEN", "GITLAB=glpat-abcdefghij0123456789", "glpat-abcdefghij0123456789"),
    ("SLACK_TOKEN", "slack: xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
    (
        "SLACK_WEBHOOK",
        "url https://hooks.slack.com/services/T0ABC123/B0XYZ987/abcDEF123456",
        "T0ABC123",
    ),
    ("GOOGLE_API_KEY", "key=AIzaSyA1234567890abcdefghijklmnopqrstuv", "AIzaSyA1234"),
    ("STRIPE_KEY", "stripe = 'sk_live_" + "x9Y8" * 6 + "'", "sk_live_x9Y8"),
    ("ANTHROPIC_KEY", "ANTHROPIC_API_KEY=sk-ant-api03-" + "Ab1" * 12, "sk-ant-api03-Ab1"),
    ("OPENAI_KEY", "OPENAI = sk-proj-" + "Zq7" * 12, "sk-proj-Zq7"),
    ("JWT", "auth eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4fwpMeJf36", "eyJhbGci"),
    ("AZURE_STORAGE_KEY", "AccountKey=" + "A1b2C3d4" * 6 + "==", "AccountKey=A1b2"),
    ("CONNECTION_STRING_PASSWORD", "Server=db;Password=hunter22;", "hunter22"),
    ("GENERIC_SECRET", 'client_secret = "s3cr3tvalue123"', "s3cr3tvalue123"),
    ("HIGH_ENTROPY", 'signing = "q8Vn2LdE7RtZ0pXw3HgK9mBc5YsJ1uFa"', "q8Vn2LdE7RtZ0pXw"),
    ("PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----", "BEGIN RSA PRIVATE KEY"),
]

PII_SAMPLES = [
    ("EMAIL", "contact jane.doe@contoso.io for access", "jane.doe@contoso.io"),
    ("CREDIT_CARD", "card 4111 1111 1111 1111 on file", "4111 1111 1111 1111"),
    ("CREDIT_CARD", "pan=5555-5555-5555-4444", "5555-5555-5555-4444"),
    ("US_SSN", "ssn 078-05-1120 in the record", "078-05-1120"),
    ("IBAN", "pay to GB82 WEST 1234 5698 7654 32 today", "GB82 WEST"),
]


@pytest.mark.parametrize(("kind", "line", "leaked"), SECRET_SAMPLES + PII_SAMPLES)
def test_sample_is_caught(kind: str, line: str, leaked: str) -> None:
    out = RegexSecretRedactor().redact("sample.py", line + "\n")
    assert out.counts.get(kind, 0) >= 1, out.counts
    assert leaked not in out.text
    assert out.text.count("\n") == 1


@pytest.mark.parametrize(
    "line",
    [
        "example email user@example.com in docs",
        "author 12345678+bot@users.noreply.github.com",
        "card 4111 1111 1111 1112 is not a valid Luhn number",  # checksum fails
        "iban GB82 WEST 1234 5698 7654 33 has a bad checksum",
        "ids 000-12-3456 are never issued",  # invalid SSN area
        'label = "Please enter your account number now"',  # spaces: not a token
        'name = "getUserAccountBalanceFromLedger"',  # identifier, low entropy
        'sha = "3f786850e387550fdab836ed7e6dc881de23001b"',  # git sha: hex, below entropy bar
        'uuid = "550e8400-e29b-41d4-a716-446655440000"',
    ],
)
def test_non_sensitive_text_is_not_redacted(line: str) -> None:
    out = RegexSecretRedactor().redact("ok.py", line + "\n")
    assert out.text == line + "\n"
    assert out.counts == {}


def test_placeholders_keep_line_positions() -> None:
    text = "a = 1\nb = 2\nkey = 'AKIAIOSFODNN7EXAMPLE'\nc = 3\n\n\nmail = 'x@contoso.io'\n"
    out = RegexSecretRedactor().redact("cfg.py", text)
    lines = out.text.split("\n")
    assert len(lines) == len(text.split("\n"))
    assert lines[0] == "a = 1"
    assert lines[1] == "b = 2"
    assert lines[3] == "c = 3"
    assert "[REDACTED:AWS_KEY]" in lines[2]
    assert "[REDACTED:EMAIL]" in lines[6]


def test_citation_line_ranges_are_unchanged_by_redaction() -> None:
    # A citation points at (start_line, end_line). Redacting every secret on one line must not
    # move any line of the file, or the citation would point at the wrong code.
    dirty = "def f():\n    return 1\n\ndef g():\n    k = 'AKIAIOSFODNN7EXAMPLE'\n    return 2\n"
    clean = dirty.replace("AKIAIOSFODNN7EXAMPLE", "not-a-secret-value")
    out_lines = RegexSecretRedactor().redact("m.py", dirty).text.split("\n")
    clean_lines = clean.split("\n")
    assert len(out_lines) == len(clean_lines)
    for got, want in zip(out_lines, clean_lines, strict=True):
        if "REDACTED" not in got:
            assert got == want


def test_private_key_block_is_fully_redacted() -> None:
    text = (
        "x\n-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3\nBBBB\n"
        "-----END OPENSSH PRIVATE KEY-----\ny\n"
    )
    out = RegexSecretRedactor().redact("k.txt", text)
    assert "AAAAB3" not in out.text
    assert "BBBB" not in out.text
    assert out.counts == {"PRIVATE_KEY": 1}
    assert out.text.split("\n")[-2] == "y"


def test_allowlist_can_be_extended() -> None:
    r = RegexSecretRedactor(allow=(re.compile(r"[^@\s]+@corp\.internal"),))
    assert r.redact("a.py", "x@corp.internal\n").counts == {}
    assert r.redact("a.py", "x@contoso.io\n").counts == {"EMAIL": 1}


def test_entropy_helper() -> None:
    assert _looks_random("q8Vn2LdE7RtZ0pXw3HgK9mBc5YsJ1uFa")
    assert not _looks_random("aaaaaaaaaaaaaaaaaaaaaaaa")


# ---------------------------------------------------------------- fail closed


def test_file_over_limit_is_refused() -> None:
    with pytest.raises(RedactionError, match="too large"):
        RegexSecretRedactor(max_chars=10).redact("big.txt", "x" * 11)


def test_detector_error_is_refused_not_passed_through() -> None:
    def boom(_: str) -> bool:
        raise ValueError("detector bug")

    broken = Rule("EMAIL", re.compile(r"\bx\b"), validate=boom)
    with pytest.raises(RedactionError, match=r"redaction failed for f\.py"):
        RegexSecretRedactor(rules=(broken,)).redact("f.py", "x\n")


def test_default_rules_compile_and_have_kinds() -> None:
    kinds = [r.kind for r in DEFAULT_RULES]
    assert len(kinds) == len(set(kinds))
    assert {"AWS_KEY", "EMAIL", "CREDIT_CARD", "HIGH_ENTROPY"} <= set(kinds)
