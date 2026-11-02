# Change Request CR-102: reject by default on clearQueue

Date: 2026-02-14
Owner: LimitKit Product Owner
From: LimitKit Tech Lead
To: Change Advisory Board
Status: Rejected on 2026-02-17

## Description

Proposal to make `clearQueue()` reject pending promises by default instead of using an opt-in option.

## Reason for rejection

It is a breaking change for callers that rely on silent discard, and would force a major release. CR-101 supersedes this proposal with an opt-in default of `false`.
