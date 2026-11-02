# Testing Rules

Rules for verifying LimitKit changes.

## Test stack

The tools used to run checks.

### Tools

Tests run with `npm test`, which executes `xo && ava && tsd`. Runtime tests live in `test.js` and type tests in `index.test-d.ts`.

## Coverage expectations

Minimum behavior that tests must cover.

### Required test cases

Any change to queueing behavior needs tests for concurrency 1, concurrency 4, error continuation, `activeCount`/`pendingCount`, `clearQueue`, and `map`.

### Timing assertions

Timing tests use `in-range` and `time-span` with a tolerance. Do not use fixed sleeps longer than 100 ms in unit tests.

## Regression suite

Tests that must never be removed.

### Unhandled rejection checks

Every `map` change must keep the test proving no unhandled rejection occurs when the iterable throws mid-iteration.
