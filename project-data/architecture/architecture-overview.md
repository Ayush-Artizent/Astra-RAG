# Architecture Overview

Date: 2026-02-01
Owner: LimitKit Tech Lead

## Core design

`pLimit` in `index.js` creates a closure holding a Queue from `yocto-queue` and a counter `activeCount`. Calling the limiter enqueues a task; `resumeNext` starts it when `activeCount < concurrency`.

## Task execution

The internal `run` function calls the task inside an async wrapper, resolves the caller promise immediately with that result, then awaits it in a try/catch so failures do not stop the queue. It then calls `next`, which decrements `activeCount` and resumes the next task.

## Public members

`activeCount`, `pendingCount`, `clearQueue`, `concurrency` (getter and setter) and `map` are defined with `Object.defineProperties` on the limiter function.

## Validation

`validateConcurrency` accepts integers above zero or `Number.POSITIVE_INFINITY`, otherwise throws TypeError.

## Known limitation

Calling the same limiter from inside a task it limits can deadlock, because inner tasks wait for slots held by outer tasks. Use a separate limiter.
