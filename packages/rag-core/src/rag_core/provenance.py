"""Citation construction (§8 tier 1). Deep links are pinned to the commit SHA."""

from __future__ import annotations

from urllib.parse import quote

from rag_core.schemas import Chunk, Citation, GitHost, Scores


def deep_link(
    host: GitHost, repo_url: str, commit_sha: str, path: str, start: int, end: int
) -> str:
    """Build a SHA-pinned deep link so the citation shows what the retriever saw."""
    base = repo_url.rstrip("/")
    match host:
        case GitHost.GITLAB:
            return f"{base}/-/blob/{commit_sha}/{quote(path)}#L{start}-{end}"
        case GitHost.AZURE_REPOS:
            return (
                f"{base}?path=/{quote(path)}&version=GC{commit_sha}"
                f"&line={start}&lineEnd={end}&lineStartColumn=1&lineEndColumn=1"
            )


def cite(chunk: Chunk, scores: Scores, url: str | None = None) -> Citation:
    return Citation(
        chunk_id=chunk.chunk_id,
        repo=chunk.repo,
        path=chunk.path,
        commit_sha=chunk.commit_sha,
        lines=(chunk.start_line, chunk.end_line),
        content_hash=chunk.content_hash,
        url=url,
        heading_path=chunk.heading_path,
        scores=scores,
    )
