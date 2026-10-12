"""Immutable, content-addressed snapshots so old citations still resolve (§8)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BlobStore(Protocol):
    async def put_snapshot(self, content_hash: str, text: str) -> str:
        """Idempotent write keyed by content hash; returns the snapshot URI."""
        ...

    async def get_snapshot(self, uri: str) -> str: ...
