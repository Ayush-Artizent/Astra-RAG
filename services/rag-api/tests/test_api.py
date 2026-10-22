import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from rag_api.deps import get_backends
from rag_api.main import create_app
from rag_api.retrieval import service
from rag_core.redaction import RegexSecretRedactor, Rule

A = {"Authorization": "Bearer dev-key-tenant-a"}
B = {"Authorization": "Bearer dev-key-tenant-b"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_backends.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_backends.cache_clear()


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_requires_auth(client: TestClient) -> None:
    assert client.post("/v1/tools/search_code", json={"query": "refund"}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert (
        client.post("/v1/tools/search_code", json={"query": "refund"}, headers=bad).status_code
        == 401
    )


def test_search_code_returns_citations_and_snapshot(client: TestClient) -> None:
    r = client.post(
        "/v1/tools/search_code", json={"query": "RefundPolicy is_eligible", "k": 3}, headers=A
    )
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"]
    assert body["snapshot"] == {"payments-service": "demo0001"}
    top = body["results"][0]
    assert top["symbol"] == "RefundPolicy.is_eligible"
    cit = top["citation"]
    assert cit["commit_sha"] == "demo0001"
    assert cit["url"].endswith("/-/blob/demo0001/src/refunds/policy.py#L1-4")
    assert cit["scores"]["bm25"] is not None


def test_search_docs_finds_golden_brd(client: TestClient) -> None:
    r = client.post("/v1/tools/search_docs", json={"query": "refund eligibility"}, headers=A)
    res = r.json()["results"]
    assert res
    assert res[0]["citation"]["heading_path"] == ["Refunds v2 BRD", "Eligibility"]


@pytest.mark.tenancy
def test_tenant_id_in_body_is_rejected(client: TestClient) -> None:
    r = client.post("/v1/tools/search_code", json={"query": "x", "tenant_id": "t_dev_b"}, headers=A)
    assert r.status_code == 422


@pytest.mark.tenancy
@pytest.mark.parametrize("tool", ["search_code", "search_docs"])
def test_no_cross_tenant_leak_via_api(client: TestClient, tool: str) -> None:
    # Tenant B's corpus mentions refunds; tenant A must never see it, and vice versa.
    a = client.post(
        f"/v1/tools/{tool}", json={"query": "refunds never allowed ledger"}, headers=A
    ).json()
    assert all(r["citation"]["repo"] != "ledger" for r in a["results"])
    b = client.post(
        f"/v1/tools/{tool}", json={"query": "RefundPolicy refund eligibility"}, headers=B
    ).json()
    assert all(r["citation"]["repo"] == "ledger" for r in b["results"])


@pytest.mark.tenancy
def test_list_repos_scoped(client: TestClient) -> None:
    repos = {
        r["repo"] for r in client.post("/v1/tools/list_repos", json={}, headers=B).json()["repos"]
    }
    assert repos == {"ledger"}


def test_query_is_redacted_before_trace(client: TestClient) -> None:
    query = "refund AKIAIOSFODNN7EXAMPLE jane.doe@contoso.io"
    r = client.post("/v1/tools/search_code", json={"query": query, "k": 3}, headers=A)
    rec = get_backends().traces.traces[r.json()["trace_id"]]  # type: ignore[attr-defined]
    assert "AKIA" not in rec.query_original
    assert "contoso" not in rec.query_original
    assert rec.query_original == "refund [REDACTED:AWS_KEY] [REDACTED:EMAIL]"


def test_query_trace_fails_closed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_: str) -> bool:
        raise ValueError("detector bug")

    broken = RegexSecretRedactor(rules=(Rule("EMAIL", re.compile(r"\bx\b"), validate=boom),))
    monkeypatch.setattr(service, "_query_redactor", broken)
    r = client.post("/v1/tools/search_code", json={"query": "refund x", "k": 3}, headers=A)
    assert r.status_code == 200  # retrieval still answers; only the trace is withheld
    rec = get_backends().traces.traces[r.json()["trace_id"]]  # type: ignore[attr-defined]
    assert rec.query_original == "[REDACTED:REDACTION_FAILED]"
