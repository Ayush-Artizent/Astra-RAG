# Email: Proposed default size for platform caches

From: Platform Architect
To: Core Collections Lead; QA Lead
Date: 2025-06-12
Subject: Proposed default size for platform caches

## Proposal

I propose that the CacheFactory in com.acme.platform.guava.cache sets maximumSize to 10,000 entries by default. The upstream CacheBuilder default is unbounded, which has caused two out-of-memory incidents in the order service. The initialCapacity default stays at 16 and concurrencyLevel at 4 for now.

## Next step

I will record this as ADR-014 once the QA Lead confirms the benchmark numbers. Open: confirm whether recordStats() should be enabled by default.
