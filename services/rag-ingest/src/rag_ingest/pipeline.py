"""Incremental indexing pipeline (§4.1 steps 3-10). Never re-index the world.

Idempotency: every step before ``commit_pointer`` is safe to repeat. A failed job is retried
from the *old* pointer, so partial writes are simply overwritten on the next attempt.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from rag_core.ids import chunk_id, content_hash
from rag_core.interfaces import (
    BlobStore,
    ChunkStore,
    Embedder,
    FileChangeKind,
    GitHostClient,
    GraphStore,
    RedactionError,
    Redactor,
    StateStore,
)
from rag_core.schemas import Chunk, Edge, RedactionInfo, TrustTier
from rag_core.tenancy import TenantContext, tenant_scope
from rag_ingest.jobs import IngestJob
from rag_ingest.stages.filter import FileFilter
from rag_parsers import ParserRegistry, SourceFile
from rag_parsers.detect import detect_doc_type, detect_language, is_test_path

log = logging.getLogger(__name__)


class PointerConflictError(RuntimeError):
    """Another job advanced ``last_indexed_sha`` first; this job's result is discarded."""


@dataclass
class IngestReport:
    job_id: str
    repo: str
    old_sha: str | None
    new_sha: str
    full_compare: bool = False
    files_changed: int = 0
    files_indexed: int = 0
    files_deleted: int = 0
    files_filtered: int = 0
    files_failed_redaction: int = 0
    chunks_total: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    redactions: Counter[str] = field(default_factory=Counter)  # counts by type, never values


@dataclass
class IndexPipeline:
    git: GitHostClient
    state: StateStore
    chunks: ChunkStore
    graph: GraphStore
    blobs: BlobStore
    embedder: Embedder
    redactor: Redactor
    parsers: ParserRegistry
    file_filter: FileFilter = field(default_factory=FileFilter)
    embed_batch_size: int = 64

    async def run(self, job: IngestJob) -> IngestReport:
        with tenant_scope(TenantContext(job.tenant_id, principal="rag-ingest")):
            return await self._run(job)

    async def _run(self, job: IngestJob) -> IngestReport:
        repo_state = await self.state.get_repo(job.repo)
        if repo_state is None:
            raise LookupError(f"repo not registered: {job.repo}")
        old = repo_state.last_indexed_sha
        report = IngestReport(job.job_id, job.repo, old, job.new_sha)
        if old == job.new_sha:
            return report

        # Step 3 + 4.2: diff; force-push / history rewrite -> full tree comparison.
        base = old
        if old is not None and not await self.git.is_ancestor(job.repo, old, job.new_sha):
            base, report.full_compare = None, True
        changes = await self.git.diff(job.repo, base, job.new_sha)
        report.files_changed = len(changes)

        removed = [c.old_path or c.path for c in changes if c.kind is FileChangeKind.DELETED]
        removed += [c.old_path for c in changes if c.kind is FileChangeKind.RENAMED and c.old_path]
        touched = [c.path for c in changes if c.kind is not FileChangeKind.DELETED]

        new_chunks: list[Chunk] = []
        new_edges: list[Edge] = []
        for path in touched:
            built = await self._process_file(job, path, repo_state.trust_tier, report)
            if built is not None:
                new_chunks.extend(built[0])
                new_edges.extend(built[1])

        # Step 7: reuse vectors for unchanged content; embed only what's new.
        vectors = await self._vectors_for(new_chunks, report)

        # Step 8: snapshots first (immutable), then index + graph.
        final: list[Chunk] = []
        for c in new_chunks:
            uri = await self.blobs.put_snapshot(c.content_hash, c.text)
            final.append(c.model_copy(update={"snapshot_uri": uri}))
        stale_paths = removed + touched  # touched files are fully replaced by their new chunks
        await self.chunks.delete_paths(job.repo, stale_paths)
        await self.graph.delete_for_paths(job.repo, stale_paths)
        if final:
            await self.chunks.upsert(final, [vectors[c.content_hash] for c in final])
        if new_edges:
            await self.graph.upsert_edges(job.repo, new_edges)
        report.files_deleted = len(removed)
        report.chunks_total = len(final)

        # Step 9: commit pointer only after everything above succeeded.
        if not await self.state.commit_pointer(job.repo, old, job.new_sha):
            raise PointerConflictError(f"{job.repo}: pointer moved during job {job.job_id}")
        log.info(
            "indexed", extra={"tenant_id": job.tenant_id, "repo": job.repo, "job_id": job.job_id}
        )
        return report

    async def _process_file(
        self, job: IngestJob, path: str, tier: TrustTier, report: IngestReport
    ) -> tuple[list[Chunk], list[Edge]] | None:
        if not self.file_filter.should_index(path):
            report.files_filtered += 1
            return None
        raw = await self.git.read_file(job.repo, job.new_sha, path)
        if not self.file_filter.should_index(path, size=len(raw), head=raw[:8192]):
            report.files_filtered += 1
            return None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            report.files_filtered += 1
            return None

        # Step 5: redact BEFORE anything else touches the text. Fail closed.
        try:
            red = self.redactor.redact(path, text)
        except RedactionError:
            report.files_failed_redaction += 1
            log.warning(
                "redaction failed; file skipped", extra={"repo": job.repo, "job_id": job.job_id}
            )
            return None
        report.redactions.update(red.counts)

        # Step 6: parse + chunk + content hash.
        language = detect_language(path)
        src = SourceFile(
            path, red.text, language, detect_doc_type(path, golden=tier is TrustTier.GOLDEN)
        )
        plugin = self.parsers.resolve(path, language)
        info = RedactionInfo(count=red.total, types=sorted(red.counts))
        chunks = []
        for pc in plugin.chunk(src):
            h = content_hash(pc.text)
            chunks.append(
                Chunk(
                    chunk_id=chunk_id(job.tenant_id, job.repo, path, pc.symbol, h),
                    tenant_id=job.tenant_id,
                    repo=job.repo,
                    path=path,
                    commit_sha=job.new_sha,
                    start_line=pc.start_line,
                    end_line=pc.end_line,
                    content_hash=h,
                    text=pc.text,
                    language=language,
                    symbol=pc.symbol,
                    signature=pc.signature,
                    doc_type=src.doc_type,
                    trust_tier=tier,
                    heading_path=pc.heading_path,
                    is_test=is_test_path(path),
                    redaction=info,
                    embedding_model=self.embedder.model_id,
                )
            )
        edges = [
            Edge(
                tenant_id=job.tenant_id,
                src=e.src,
                dst=e.dst,
                kind=e.kind,
                confidence=e.confidence,
                source=e.source,
                commit_sha=job.new_sha,
            )
            for e in plugin.edges(src)
        ]
        report.files_indexed += 1
        return chunks, edges

    async def _vectors_for(
        self, chunks: list[Chunk], report: IngestReport
    ) -> dict[str, list[float]]:
        hashes = list({c.content_hash for c in chunks})
        vectors = await self.chunks.existing_vectors(hashes, self.embedder.model_id)
        report.chunks_reused = sum(1 for c in chunks if c.content_hash in vectors)
        todo = {c.content_hash: c for c in chunks if c.content_hash not in vectors}
        items = list(todo.values())
        for i in range(0, len(items), self.embed_batch_size):
            batch = items[i : i + self.embed_batch_size]
            # Embed header + text: the contextual header makes chunks self-describing (§5).
            embedded = await self.embedder.embed(
                [f"{c.contextual_header()}\n{c.text}" for c in batch]
            )
            vectors.update({c.content_hash: v for c, v in zip(batch, embedded, strict=True)})
        report.chunks_embedded = len(items)
        return vectors
