# Hashing Requirements

Date: 2025-09-03
Owner: Security Architect
Status: Approved

## REQ-HASH-001 algorithms

Integrity digests shall use Hashing.sha256(). Partitioning keys shall use Hashing.murmur3_128().

## REQ-HASH-002 sharding

Shard routing shall use Hashing.consistentHash(hashCode, 64) so that growing from 64 to 65 shards moves about 1/65 of keys.

## REQ-HASH-003 bloom filters

Bloom filters shall specify expectedInsertions and fpp explicitly. Production fpp shall be 0.01 or lower.

## REQ-HASH-004 hash streams

File checksums shall use HashingInputStream or Files.asByteSource(file).hash(Hashing.sha256()).
