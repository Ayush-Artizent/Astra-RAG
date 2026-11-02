# Meeting Notes: Hashing policy session

Date: 2025-08-12
Owner: Security Architect
Attendees: Security Architect; Core Collections Lead; Release Manager

## Discussion

Group discussed Hashing.md5, sha1, murmur3_128 and goodFastHash. Murmur3 is not a cryptographic hash and must not be used for integrity or secrets.

## Decisions

ADR-016: sha256 for deduplication keys and murmur3_128 for partitioning. Hashing.consistentHash is used for shard routing across 64 shards.

## Open items

Open: whether sipHash24 is needed for hash-flooding defense in the public map facade.
