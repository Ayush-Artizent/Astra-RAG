# Change Request CR-2026-033: Deprecate use of EventBus in new services

Date: 2026-05-14
Owner: Platform Architect
Status: Rejected on 2026-05-26

## Summary

Proposal to deprecate com.google.common.eventbus.EventBus for new services in favor of the internal broker.

## Rejection reason

Board decided the in-process EventBus remains allowed for in-process notification. Open: revisit after the broker reaches general availability.
