import httpx
import pytest

from astra_rag_sdk import AstraRagClient, AstraRagError
from rag_api.deps import get_backends
from rag_api.main import create_app
from rag_core.schemas import CallerInfo


@pytest.fixture
async def app():
    get_backends.cache_clear()
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application
    get_backends.cache_clear()


async def test_sdk_roundtrip_against_real_app(app) -> None:
    transport = httpx.ASGITransport(app=app)
    caller = CallerInfo(platform="test", agent_run_id="run-1", ticket_id="PAY-42")
    async with AstraRagClient(
        "http://test", "dev-key-tenant-a", caller=caller, transport=transport
    ) as rag:
        resp = await rag.search_code("RefundPolicy is_eligible", k=2)
        assert resp.results
        assert resp.results[0].citation.commit_sha == "demo0001"
        repos = await rag.list_repos()
        assert {r.repo for r in repos.repos} == {"payments-service", "golden-docs"}


async def test_sdk_raises_on_bad_token(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with AstraRagClient("http://test", "wrong", transport=transport) as rag:
        with pytest.raises(AstraRagError) as e:
            await rag.search_code("x")
    assert e.value.status == 401
