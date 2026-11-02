# ADR-014 Cache default sizing

Date: 2025-06-24
Owner: Platform Architect
Status: Superseded by ADR-019

## Status

Superseded by ADR-019. Original decision kept for history.

## Decision

CacheFactory sets maximumSize 10,000 entries by default, initialCapacity 16 and concurrencyLevel 4.

## Consequences

Bounded memory but a measured hit ratio of 83 percent for the order service.
