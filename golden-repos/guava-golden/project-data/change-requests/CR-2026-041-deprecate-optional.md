# Change Request CR-2026-041: Deprecate Guava Optional in platform APIs

Date: 2026-07-08
Owner: Core Collections Lead
Status: Approved on 2026-07-21

## Summary

Platform APIs must use java.util.Optional. Guava Optional in com.google.common.base remains for upstream compatibility only.

## Impact

Removal from public APIs follows the 12 month deprecation window; earliest removal release is 34.2.0-jre-acme.1.
