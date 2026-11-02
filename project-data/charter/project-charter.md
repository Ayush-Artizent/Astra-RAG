# Project Charter: LimitKit

Date: 2026-01-10
Owner: LimitKit Product Owner

## Vision

Provide a tiny, dependable way to run promise-returning and async functions with limited concurrency, usable in Node.js and browsers.

## Objectives

Keep the API small, keep a single runtime dependency, and make behavior predictable under errors and queue teardown.

## Success criteria

Zero unhandled rejections from `map`, all tests green on `npm test`, and adoption by at least five internal services in the first year.

## Out of scope

Rate limiting by time window, queue pausing and priorities. Teams needing those use a full queue library such as p-queue.
