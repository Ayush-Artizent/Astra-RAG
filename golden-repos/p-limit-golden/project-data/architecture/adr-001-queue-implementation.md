# ADR-001: Use yocto-queue for the pending queue

Date: 2026-01-25
Owner: LimitKit Tech Lead
Status: Accepted

## Context

A plain array with `shift()` is O(n) per dequeue, which hurts when thousands of tasks are pending.

## Decision

Use `yocto-queue`, a linked-list queue with O(1) enqueue and dequeue, version `^1.2.1`. This is the single allowed runtime dependency.

## Consequences

A small dependency is added. Queue size is read through `queue.size`, used by `pendingCount`.

## Open

Open: evaluate an internal queue to remove the dependency if `yocto-queue` becomes unmaintained.
