# Cache Requirements v2

Date: 2026-02-15
Owner: Product Owner
Status: Approved

## REQ-CACHE-004 default size

Platform caches shall default to maximumSize 25,000 entries as decided in ADR-019. Teams caching values over 64 KB may choose a weigher with maximumWeight. Open: weigher defaults are to decide.

## REQ-CACHE-005 expiry

Caches holding customer-derived data shall set expireAfterWrite of at most 24 hours. The platform default is 60 minutes.

## REQ-CACHE-006 statistics

Caches shall call recordStats() so hit rate, eviction count and average load penalty are exported to the metrics platform.

## REQ-CACHE-007 refresh

LoadingCache instances shall support refreshAfterWrite with asynchronous reloading through CacheLoader.asyncReloading and a dedicated executor.
