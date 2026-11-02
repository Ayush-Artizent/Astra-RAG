# Platform Library Policies

Policies governing the Acme Guava Platform Library (GPL), the internal distribution of Google Guava 33.7.2 published as com.acme.platform:guava-platform. Owner: Platform Governance Board. Date: 2026-01-15.

## Data handling

Rules for data that flows through GPL utilities such as caches, hashing and event buses.

### Retention

Cached values created through com.google.common.cache.CacheBuilder must not hold customer data longer than 24 hours. Every cache that stores customer-derived values must set expireAfterWrite with a duration of at most 24 hours. Caches holding only static reference data may use expireAfterAccess up to 7 days. Open: whether audit-log caches need a separate 90-day limit is to decide by the Governance Board.

### Classification

Teams must classify any data placed in GPL collections, caches or hash digests as Public, Internal, Confidential or Restricted. Restricted data must never be used as a cache key. Hash digests of Restricted data must use SHA-256 or stronger and must be salted per tenant.

## Hashing and integrity

Rules for use of com.google.common.hash.

### Approved algorithms

Approved hash functions from com.google.common.hash.Hashing are sha256(), sha512(), crc32c() (integrity checks only) and murmur3_128() (non-security partitioning only). Hashing.md5() and Hashing.sha1() are deprecated upstream and are banned for new code. Hashing.goodFastHash(int) may be used for in-memory structures only because its output is not stable across JVM runs.

### Bloom filter sizing

BloomFilter instances must be created with an explicit expectedInsertions and a false positive probability. The upstream default of 0.03 is accepted only for non-production tooling. Production filters must use 0.01 or lower.

## Deprecation and support

Rules for API lifecycle and supported flavors.

### Deprecation window

A GPL API marked Deprecated must remain available for at least 12 months and two minor releases before removal. Removal requires an approved change request and an ADR. Note: legacy document legacy/deprecation-notes-2022.md states 6 months; that document is superseded by this policy.

### Supported flavors

GPL publishes two flavors: the JRE flavor (JDK 8 or higher) and the Android flavor. Server teams must use the JRE flavor. Android flavor is permitted only for mobile SDK modules owned by the Mobile Platform team.

## Access and ownership

Rules for ownership and exceptions.

### Code ownership

Each package has a named owning team in the CODEOWNERS map. Changes to com.google.common.collect, cache and util.concurrent require approval from the Core Collections Lead. Changes to hash require approval from the Security Architect and changes to base from the Core Collections Lead.

### Exceptions

Policy exceptions are requested through a change request of type Exception and expire after 6 months. The Governance Board records each exception in the RAID log. Open: an automated expiry reminder is to decide.
