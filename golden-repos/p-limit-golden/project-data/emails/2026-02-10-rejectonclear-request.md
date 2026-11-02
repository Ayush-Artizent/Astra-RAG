# Email: Request for rejectOnClear option

Date: 2026-02-10
From: Payments Platform Lead
To: LimitKit Product Owner
Cc: LimitKit Tech Lead

## Request

Our batch settlement job awaits `Promise.all` over limited tasks. After we call `limit.clearQueue()` at shutdown, the pending promises never settle and the job hangs. We need pending promises to reject when the queue is cleared.

## Proposed behavior

An option `rejectOnClear`, boolean, default `false` so existing callers are unaffected. When true, `clearQueue()` rejects every pending promise with an abort error.

## Open

Open: should `limitFunction` also accept `rejectOnClear`? The Payments team assumes yes.
