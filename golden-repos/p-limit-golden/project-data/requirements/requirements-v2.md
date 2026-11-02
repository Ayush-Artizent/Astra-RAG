# Requirements v2 (CURRENT)

Date: 2026-03-05
Owner: LimitKit Product Owner
Status: Current. Supersedes requirements v1 dated 2026-01-15.

## Functional requirements

REQ-001 The library exposes `pLimit(concurrency)` as default export and `limitFunction` as named export.
REQ-002 `clearQueue()` discards pending tasks, and rejects them when `rejectOnClear` is true.
REQ-003 Concurrency must be an integer of 1 or more, or `Infinity`. Zero is rejected with TypeError.
REQ-004 The limiter exposes `activeCount`, `pendingCount`, a `concurrency` getter and setter, and `map(iterable, mapper)`.

## Non-functional requirements

NFR-001 Minimum Node.js version is 20.
NFR-002 One runtime dependency, `yocto-queue` at `^1.2.1`.

## Open items

Open: confirm a maximum supported queue length. No limit is enforced today.
