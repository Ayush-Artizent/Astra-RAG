import pytest

from rag_core.ids import chunk_id, content_hash
from rag_core.interfaces import SearchFilters, SearchMode
from rag_core.memory import FakeEmbedder, MemoryChunkStore
from rag_core.schemas import Chunk
from rag_core.tenancy import TenantContext, TenantIsolationError, tenant_scope

pytestmark = pytest.mark.tenancy

A = TenantContext("t_a", "sp-a")
B = TenantContext("t_b", "sp-b")


def _chunk(tenant: str, text: str) -> Chunk:
    h = content_hash(text)
    return Chunk(
        chunk_id=chunk_id(tenant, "repo", "a.py", None, h),
        tenant_id=tenant,
        repo="repo",
        path="a.py",
        commit_sha="abc",
        start_line=1,
        end_line=1,
        content_hash=h,
        text=text,
    )


async def test_store_fails_closed_without_tenant() -> None:
    store = MemoryChunkStore()
    with pytest.raises(TenantIsolationError):
        await store.search(SearchMode.LEXICAL, text="x", filters=SearchFilters(), k=5)


async def test_cannot_write_other_tenants_chunk() -> None:
    store = MemoryChunkStore()
    with tenant_scope(A), pytest.raises(TenantIsolationError):
        await store.upsert([_chunk("t_b", "secret_b")], [[0.0]])


async def test_no_cross_tenant_reads() -> None:
    store, emb = MemoryChunkStore(), FakeEmbedder()
    for ctx, text in ((A, "refund_policy alpha"), (B, "refund_policy bravo")):
        with tenant_scope(ctx):
            c = _chunk(ctx.tenant_id, text)
            await store.upsert([c], await emb.embed([c.text]))

    with tenant_scope(A):
        hits = await store.search(
            SearchMode.LEXICAL, text="refund_policy", filters=SearchFilters(), k=10
        )
        vec = (await emb.embed(["refund_policy"]))[0]
        hits += await store.search(SearchMode.VECTOR, vector=vec, filters=SearchFilters(), k=10)
    assert hits
    assert {h.chunk.tenant_id for h in hits} == {"t_a"}


def test_cannot_switch_tenant_inside_scope() -> None:
    with tenant_scope(A), pytest.raises(TenantIsolationError), tenant_scope(B):
        pass


def test_empty_tenant_rejected() -> None:
    with pytest.raises(TenantIsolationError):
        TenantContext(" ", "sp")
