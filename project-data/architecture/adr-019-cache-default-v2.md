# ADR-019 Cache default sizing v2

Date: 2026-02-10
Owner: Platform Architect
Status: Accepted

## Context

Benchmarks show 25,000 entries lift hit ratio from 83 to 91 percent at a p99 load latency of 4.1 ms.

## Decision

CacheFactory sets maximumSize 25,000 entries by default. concurrencyLevel moves from 4 to 8 once CR-2026-017 ships. This supersedes ADR-014.

## Open items

Open: a weigher-based default for values over 64 KB is to decide.
