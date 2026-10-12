"""LOCAL ONLY: seed the in-memory stores with a tiny two-tenant corpus so the API is usable
immediately (``uv run poe api``) and the tenancy tests have data to try to leak."""

from __future__ import annotations

from rag_api.deps import Backends
from rag_core.ids import chunk_id, content_hash
from rag_core.memory import MemoryStateStore
from rag_core.schemas import Chunk, DocType, GitHost, RepoState, TrustTier
from rag_core.tenancy import TenantContext, tenant_scope

_CORPUS: dict[str, list[tuple[str, str, str | None, DocType, str]]] = {
    "t_dev_a": [
        (
            "payments-service",
            "src/refunds/policy.py",
            "RefundPolicy.is_eligible",
            DocType.CODE,
            "class RefundPolicy:\n    def is_eligible(self, order):\n"
            "        # refunds allowed within 30 days for non-digital goods\n"
            "        return order.age_days <= 30 and not order.is_digital\n",
        ),
        (
            "payments-service",
            "src/refunds/api.py",
            "create_refund",
            DocType.CODE,
            "@router.post('/refunds')\ndef create_refund(req):\n    policy = RefundPolicy()\n"
            "    if not policy.is_eligible(req.order):\n        raise Ineligible()\n",
        ),
        (
            "golden-docs",
            "brds/refunds-v2.md",
            None,
            DocType.BRD,
            "# Refunds v2 BRD\n## Eligibility\nCustomers may request a refund within 30 days.\n",
        ),
    ],
    "t_dev_b": [
        (
            "ledger",
            "src/ledger/post.py",
            "post_entry",
            DocType.CODE,
            "def post_entry(entry):\n"
            "    # tenant B secret business rule: refunds are never allowed\n"
            "    return ledger.write(entry)\n",
        ),
    ],
}


async def seed(b: Backends) -> None:
    for tenant, docs in _CORPUS.items():
        with tenant_scope(TenantContext(tenant, "demo-seed")):
            chunks = []
            for repo, path, symbol, doc_type, text in docs:
                if isinstance(b.state, MemoryStateStore) and await b.state.get_repo(repo) is None:
                    b.state.register(
                        RepoState(
                            tenant_id=tenant,
                            repo=repo,
                            host=GitHost.GITLAB,
                            web_url=f"https://gitlab.example.com/{tenant}/{repo}",
                            trust_tier=TrustTier.GOLDEN
                            if repo == "golden-docs"
                            else TrustTier.STANDARD,
                            last_indexed_sha="demo0001",
                        )
                    )
                h = content_hash(text)
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id(tenant, repo, path, symbol, h),
                        tenant_id=tenant,
                        repo=repo,
                        path=path,
                        commit_sha="demo0001",
                        start_line=1,
                        end_line=text.count("\n") or 1,
                        content_hash=h,
                        text=text,
                        language="markdown" if path.endswith(".md") else "python",
                        symbol=symbol,
                        doc_type=doc_type,
                        heading_path=["Refunds v2 BRD", "Eligibility"]
                        if path.endswith(".md")
                        else None,
                        embedding_model=b.embedder.model_id,
                    )
                )
            vecs = await b.embedder.embed([f"{c.contextual_header()}\n{c.text}" for c in chunks])
            await b.chunks.upsert(chunks, vecs)
