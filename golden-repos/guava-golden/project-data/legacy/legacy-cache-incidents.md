# Legacy Cache Incident Summary

Date: 2025-04-18
Owner: Order Services Lead

## Incidents

Two out-of-memory incidents occurred in the order service because CacheUtil never evicted entries. Heap peaked at 7.6 GB on an 8 GB profile.

## Lesson

Caches must be bounded; this motivated REQ-CACHE-004 and ADR-014.
