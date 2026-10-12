import pytest

from rag_core.interfaces import FileChange, FileChangeKind, SearchFilters, SearchMode
from rag_core.memory import (
    FakeEmbedder,
    MemoryBlobStore,
    MemoryChunkStore,
    MemoryGraphStore,
    MemoryStateStore,
)
from rag_core.schemas import GitHost, RepoState
from rag_core.tenancy import TenantContext, tenant_scope
from rag_ingest.jobs import IngestJob
from rag_ingest.pipeline import IndexPipeline
from rag_ingest.stages.redact import RegexSecretRedactor
from rag_parsers import default_registry

TENANT = "t_1"


class FakeGit:
    """Commits are full trees; parents form a linear history unless rewritten."""

    def __init__(self) -> None:
        self.trees: dict[str, dict[str, bytes]] = {}
        self.parents: dict[str, str | None] = {}

    def commit(self, sha: str, tree: dict[str, str], parent: str | None) -> None:
        self.trees[sha] = {p: t.encode() for p, t in tree.items()}
        self.parents[sha] = parent

    async def default_branch_head(self, repo: str) -> str:
        return list(self.trees)[-1]

    async def is_ancestor(self, repo: str, old: str, new: str) -> bool:
        cur: str | None = new
        while cur is not None:
            if cur == old:
                return True
            cur = self.parents.get(cur)
        return False

    async def diff(self, repo: str, old: str | None, new: str) -> list[FileChange]:
        a, b = (self.trees[old] if old else {}), self.trees[new]
        out = [FileChange(FileChangeKind.DELETED, p) for p in a.keys() - b.keys()]
        out += [FileChange(FileChangeKind.ADDED, p) for p in b.keys() - a.keys()]
        out += [FileChange(FileChangeKind.MODIFIED, p) for p in a.keys() & b.keys() if a[p] != b[p]]
        return out

    async def read_file(self, repo: str, sha: str, path: str) -> bytes:
        return self.trees[sha][path]


@pytest.fixture
def env() -> tuple[IndexPipeline, FakeGit, MemoryChunkStore]:
    git, state, store = FakeGit(), MemoryStateStore(), MemoryChunkStore()
    with tenant_scope(TenantContext(TENANT, "test")):
        state.register(RepoState(tenant_id=TENANT, repo="payments", host=GitHost.GITLAB))
    pipe = IndexPipeline(
        git=git,
        state=state,
        chunks=store,
        graph=MemoryGraphStore(),
        blobs=MemoryBlobStore(),
        embedder=FakeEmbedder(),
        redactor=RegexSecretRedactor(),
        parsers=default_registry(),
    )
    return pipe, git, store


def job(sha: str) -> IngestJob:
    return IngestJob(tenant_id=TENANT, repo="payments", host=GitHost.GITLAB, new_sha=sha)


async def test_incremental_index_reuses_unchanged_chunks(env) -> None:
    pipe, git, store = env
    git.commit(
        "c1",
        {
            "src/refund.py": "def is_eligible():\n    return True\n",
            "README.md": "# Payments\nhello\n",
            "node_modules/x.js": "junk",
        },
        None,
    )
    r1 = await pipe.run(job("c1"))
    assert r1.files_indexed == 2
    assert r1.files_filtered == 1
    assert r1.chunks_embedded == r1.chunks_total

    git.commit(
        "c2",
        {
            "src/refund.py": "def is_eligible():\n    return True\n",
            "README.md": "# Payments\nhello world\n",
        },
        "c1",
    )
    r2 = await pipe.run(job("c2"))
    assert r2.files_changed == 2  # README modified + node_modules file deleted
    assert r2.chunks_embedded == 1  # only the README chunk is new

    with tenant_scope(TenantContext(TENANT, "test")):
        repo = await pipe.state.get_repo("payments")
        assert repo is not None
        assert repo.last_indexed_sha == "c2"
        hits = await store.search(
            SearchMode.LEXICAL, text="is_eligible", filters=SearchFilters(), k=5
        )
    assert hits
    assert hits[0].chunk.path == "src/refund.py"


async def test_secrets_redacted_before_indexing(env) -> None:
    pipe, git, store = env
    git.commit("c1", {"cfg.py": 'API_KEY = "AKIAABCDEFGHIJKLMNOP"\nx = 1\n'}, None)
    report = await pipe.run(job("c1"))
    assert report.redactions["AWS_KEY"] == 1
    with tenant_scope(TenantContext(TENANT, "test")):
        hits = await store.search(SearchMode.LEXICAL, text="API_KEY", filters=SearchFilters(), k=5)
    assert hits
    assert "AKIA" not in hits[0].chunk.text
    assert "[REDACTED:AWS_KEY]" in hits[0].chunk.text


async def test_force_push_falls_back_to_full_compare(env) -> None:
    pipe, git, _ = env
    git.commit("c1", {"a.py": "x = 1\n"}, None)
    await pipe.run(job("c1"))
    git.commit("c9", {"a.py": "x = 2\n"}, None)  # rewritten history: c1 not an ancestor
    report = await pipe.run(job("c9"))
    assert report.full_compare
