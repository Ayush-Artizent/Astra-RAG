"""Tenant isolation: the single enforcement point (§9).

Rule: data-access code never accepts ``tenant_id`` as a parameter. It reads it from the
ambient :class:`TenantContext`, which is set exactly once per request/job from the
*authenticated credential* (API) or the *queued job envelope* (ingest). If no tenant is
bound, every store call fails closed with :class:`TenantIsolationError`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


class TenantIsolationError(RuntimeError):
    """Raised when tenant-scoped data is touched without a bound tenant, or across tenants."""


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    principal: str  # service principal / client id that authenticated; for audit

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.tenant_id.strip():
            raise TenantIsolationError("tenant_id must be a non-empty string")


_current: ContextVar[TenantContext | None] = ContextVar("astra_tenant", default=None)


def current_tenant() -> TenantContext:
    ctx = _current.get()
    if ctx is None:
        raise TenantIsolationError("no tenant bound to the current context")
    return ctx


def require_tenant_id() -> str:
    return current_tenant().tenant_id


@contextmanager
def tenant_scope(ctx: TenantContext) -> Iterator[TenantContext]:
    """Bind a tenant for the duration of a request or job. Nesting a *different* tenant is a bug."""
    existing = _current.get()
    if existing is not None and existing.tenant_id != ctx.tenant_id:
        raise TenantIsolationError(
            f"attempted to switch tenant inside an active scope ({existing.tenant_id!r})"
        )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def assert_same_tenant(record_tenant_id: str) -> None:
    """Defence in depth: call on every record read back from a store before returning it."""
    if record_tenant_id != require_tenant_id():
        raise TenantIsolationError("record belongs to a different tenant")
