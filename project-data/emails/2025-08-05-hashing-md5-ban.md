# Email: Banning Hashing.md5 and Hashing.sha1

From: Security Architect
To: Core Collections Lead; Release Manager
Date: 2025-08-05
Subject: Banning Hashing.md5 and Hashing.sha1

## Position

Hashing.md5() and Hashing.sha1() are deprecated upstream in com.google.common.hash.Hashing. Static analysis found 41 call sites across 17 repositories. I want these banned for new code from the 32.1.3-jre-acme.2 release and removed from existing code by 2026-03-31.

## Exception

Legacy checksum interop with the partner file gateway may keep md5 until the gateway is retired. Open: the retirement date of the partner gateway is to decide.
