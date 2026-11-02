# Cryptography Use Review

Date: 2026-04-15
Owner: Compliance Lead
Status: In Review

## Scope

Review of Hashing.sha256, sha512, hmacSha256 and Hashing.crc32c usage. No encryption primitives are provided by Guava.

## Finding

Hmac functions are acceptable for message authentication when keys come from the approved key vault. Keys are never embedded in source.

## Open items

Open: confirm that sipHash24 usage does not require export classification.
