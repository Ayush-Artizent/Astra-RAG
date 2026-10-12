import pytest
from fastapi.testclient import TestClient

from rag_ingest.config import IngestSettings
from rag_ingest.stages.filter import FileFilter
from rag_ingest.stages.redact import RegexSecretRedactor
from rag_ingest.webhook import app, get_settings


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app.py", True),
        ("node_modules/lodash/index.js", False),
        ("web/dist/app.min.js", False),
        ("package-lock.json", False),
        ("assets/logo.png", False),
        ("api/openapi.yaml", True),
    ],
)
def test_filter(path: str, expected: bool) -> None:
    assert FileFilter().should_index(path) is expected


def test_filter_rejects_binary_and_large() -> None:
    f = FileFilter(max_bytes=10)
    assert not f.should_index("a.txt", size=11)
    assert not FileFilter().should_index("a.txt", size=3, head=b"a\x00b")


def test_redaction_keeps_line_count_and_never_leaks() -> None:
    text = (
        "conn = 'Server=x;Password=hunter22;'\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----\n"
        'client_secret = "s3cr3tvalue123"\n'
        "token = ghp_" + "a" * 36 + "\n"
    )
    out = RegexSecretRedactor().redact("x.py", text)
    assert out.text.count("\n") == text.count("\n")
    for leaked in ("hunter22", "MIIEow", "s3cr3tvalue123", "ghp_aaaa"):
        assert leaked not in out.text
    assert out.counts["PRIVATE_KEY"] == 1
    assert out.counts["GITHUB_TOKEN"] == 1
    assert "client_secret" in out.text  # key name kept for context


def test_webhook_rejects_bad_secret_and_accepts_good() -> None:
    app.dependency_overrides[get_settings] = lambda: IngestSettings(
        webhook_secrets_json='{"t_1": "s3cret"}'
    )
    client = TestClient(app)
    body = {
        "ref": "refs/heads/main",
        "after": "abc123",
        "project": {"path_with_namespace": "g/payments", "default_branch": "main"},
    }
    headers = {"X-Gitlab-Event": "Push Hook"}
    assert (
        client.post(
            "/webhooks/t_1/gitlab", json=body, headers={**headers, "X-Gitlab-Token": "nope"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/webhooks/t_2/gitlab", json=body, headers={**headers, "X-Gitlab-Token": "s3cret"}
        ).status_code
        == 401
    )
    ok = client.post(
        "/webhooks/t_1/gitlab", json=body, headers={**headers, "X-Gitlab-Token": "s3cret"}
    )
    assert ok.status_code == 202
    assert ok.json()["queued"] is True
    app.dependency_overrides.clear()
