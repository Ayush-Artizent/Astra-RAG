# Requirements v1 (SUPERSEDED)

Date: 2026-01-15
Owner: LimitKit Product Owner
Status: SUPERSEDED by requirements v2 dated 2026-03-05. Do not use for current decisions.

## Functional requirements

REQ-001 The library exposes `pLimit(concurrency)` returning a limiter.
REQ-002 Pending tasks are discarded silently by `clearQueue()`.
REQ-003 Concurrency of 0 is accepted and pauses the limiter.

## Non-functional requirements

NFR-001 Minimum Node.js version is 18.
NFR-002 Runtime dependencies: none.
