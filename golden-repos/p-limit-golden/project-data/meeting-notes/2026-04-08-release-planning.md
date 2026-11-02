# Meeting Notes: release planning for 7.3

Date: 2026-04-08
Owner: LimitKit Release Manager
Attendees: LimitKit Release Manager, LimitKit Tech Lead, QA Lead, Documentation Lead

## Discussion

Version 7.3.3 is the current patch line. The team reviewed LIM-231, the concurrency setter fix, which shipped in this line.

## Decisions

The `concurrency` setter keeps re-evaluating the queue through `queueMicrotask`, so raising the limit starts waiting tasks promptly.

## Actions

Documentation Lead updates the migration guide. Open: decide whether to publish benchmarks from `benchmark.js` in release notes.
