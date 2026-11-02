# ADR-016 Hashing algorithm selection

Date: 2025-08-12
Owner: Security Architect
Status: Accepted

## Decision

Deduplication keys use Hashing.sha256(). Partitioning uses Hashing.murmur3_128(). Shard routing uses Hashing.consistentHash with 64 shards. Hashing.md5() and sha1() are banned for new code.

## Consequences

sha256 costs about 3 times the CPU of murmur3_128 per key. Open: benchmark of sipHash24 for map facade is to decide.
