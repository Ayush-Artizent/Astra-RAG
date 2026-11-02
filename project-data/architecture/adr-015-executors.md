# ADR-015 Executor wrapping

Date: 2025-06-24
Owner: Platform Architect
Status: Accepted

## Decision

All platform executors are wrapped with MoreExecutors.listeningDecorator so that APIs expose ListeningExecutorService and ListenableFuture.

## Consequences

Consumers can chain with Futures.transformAsync. Direct executors are permitted only for trivial callbacks.
