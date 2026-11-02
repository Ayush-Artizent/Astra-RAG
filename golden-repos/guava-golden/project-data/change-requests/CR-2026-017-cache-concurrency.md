# Change Request CR-2026-017: Raise default cache concurrencyLevel to 8

Date: 2026-03-04
Owner: Core Collections Lead
Status: Approved on 2026-03-11

## Summary

Change the CacheFactory default concurrencyLevel from 4 to 8 for com.acme.platform.guava.cache. Upstream CacheBuilder default is 4 and splits the cache into segments by this value.

## Impact

Segment count doubles, reducing lock contention on the 16-core service profile. Memory overhead is about 3 percent. Binary compatibility is unaffected.

## Approvals

Approved by Core Collections Lead, Security Architect and QA Lead. Released in 33.7.2-jre-acme.3.
