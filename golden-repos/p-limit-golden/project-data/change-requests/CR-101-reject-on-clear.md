# Change Request CR-101: rejectOnClear option

Date: 2026-02-12
Owner: LimitKit Product Owner
From: Payments Platform Lead
To: Change Advisory Board
Status: Approved on 2026-02-17

## Description

Add `rejectOnClear` to the `pLimit` options object. Default `false`.

## Impact

Backward compatible, so a minor release. `index.d.ts` gains the option on the options object. No new dependency.

## Test impact

One new ava test for rejected pending promises after `clearQueue()`. The option on `limitFunction` was added later under CR-103.
