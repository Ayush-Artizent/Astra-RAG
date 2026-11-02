# Concurrency Requirements

Date: 2025-10-14
Owner: Platform Architect
Status: Approved

## REQ-CONC-001 futures

Asynchronous service APIs shall return ListenableFuture and use Futures.transformAsync for chained calls.

## REQ-CONC-002 executors

Thread pools shall be wrapped with MoreExecutors.listeningDecorator. Shutdown shall use MoreExecutors.shutdownAndAwaitTermination with a 30 second default timeout.

## REQ-CONC-003 services

Long-running background components shall extend AbstractScheduledService or AbstractIdleService and be managed by ServiceManager.

## REQ-CONC-004 striped locks

Per-key locking shall use Striped with 256 stripes by default. Open: Striped exposure in the public facade is to decide.
