# Email: Bloom filter for event deduplication

From: Data Platform Lead
To: Platform Architect; Security Architect
Date: 2026-05-11
Subject: Bloom filter for event deduplication

## Sizing

The ingestion pipeline will use com.google.common.hash.BloomFilter with expectedInsertions of 50,000,000 and a false positive probability of 0.001. This needs about 86 MB per filter instance and is rebuilt daily at 02:00 UTC.

## Review

The Security Architect asked whether the funnel should include the tenant id. Open: tenant-salted funnel design is to decide.
