# Change Request CR-2026-009: Upgrade base to Guava 33.7.2

Date: 2026-01-12
Owner: Release Manager
Status: Approved on 2026-01-27

## Summary

Upgrade the upstream base from 32.1.3 to 33.7.2 for both flavors.

## Impact

japicmp reports no incompatible change. Three deprecations arrive in com.google.common.io.

## Rollback

Pin guava-bom to 32.1.3-jre-acme.2.
