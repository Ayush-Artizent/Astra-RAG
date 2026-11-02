# As-Is: Legacy v3 Line

Date: 2025-11-30
Owner: LimitKit Tech Lead

## Overview

The legacy 3.x line is CommonJS, uses `require('p-limit')`, and has no `map`, no `clearQueue`, and no `concurrency` setter.

## Behavior

The legacy limiter exposes `activeCount` and `pendingCount` only. Concurrency is fixed at creation.

## Migration

Callers move to ESM with `import pLimit from 'p-limit'`. Replace manual queue teardown with `limit.clearQueue()`.

## Support status

The 3.x line receives security fixes only until 2026-12-31.
