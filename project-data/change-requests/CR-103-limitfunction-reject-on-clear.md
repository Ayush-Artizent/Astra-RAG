# Change Request CR-103: rejectOnClear for limitFunction

Date: 2026-03-10
Owner: LimitKit Product Owner
From: Payments Platform Lead
To: Change Advisory Board
Status: Approved on 2026-03-12

## Description

Allow `limitFunction(function_, {concurrency, rejectOnClear})`. The returned function exposes `clearQueue` only, not `concurrency` or `map`.

## Impact

Closes the open question from the 2026-02-10 email. Minor release.
