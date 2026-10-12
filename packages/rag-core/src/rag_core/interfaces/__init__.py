"""Everything swappable lives behind these protocols (§2 principle 6, §12).

Implementations must NOT take ``tenant_id`` as an argument: they read it from
:func:`rag_core.tenancy.require_tenant_id` so that callers can never pass or omit it.
"""

from rag_core.interfaces.blob_store import BlobStore
from rag_core.interfaces.chunk_store import ChunkStore, ScoredHit, SearchFilters, SearchMode
from rag_core.interfaces.embedder import Embedder
from rag_core.interfaces.git_host import FileChange, FileChangeKind, GitHostClient
from rag_core.interfaces.graph_store import GraphStore
from rag_core.interfaces.model_provider import ModelProvider
from rag_core.interfaces.redactor import RedactionError, RedactionResult, Redactor
from rag_core.interfaces.reranker import Reranker
from rag_core.interfaces.state_store import StateStore

__all__ = [
    "BlobStore",
    "ChunkStore",
    "Embedder",
    "FileChange",
    "FileChangeKind",
    "GitHostClient",
    "GraphStore",
    "ModelProvider",
    "RedactionError",
    "RedactionResult",
    "Redactor",
    "Reranker",
    "ScoredHit",
    "SearchFilters",
    "SearchMode",
    "StateStore",
]
