"""Deterministic, content-addressed identifiers (§4.1 step 6-7, §5)."""

from __future__ import annotations

import hashlib


def content_hash(text: str) -> str:
    """Hash of chunk content. Unchanged hash => skip re-embedding (main ingest cost saver)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(tenant_id: str, repo: str, path: str, symbol: str | None, chash: str) -> str:
    """``sha256(tenant|repo|path|symbol|content_hash)`` as defined in the chunk schema."""
    key = "|".join([tenant_id, repo, path, symbol or "", chash])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
