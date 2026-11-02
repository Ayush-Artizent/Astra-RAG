# ADR-017 Gateway rate limiting

Date: 2026-04-09
Owner: Platform Architect
Status: Accepted

## Decision

Gateway services use RateLimiter.create(200.0, 3, TimeUnit.SECONDS) so permits ramp over a 3 second warm-up. Default smooth bursty behavior allows one second of stored permits.

## Consequences

Cold downstream services are protected. The value 200 permits per second is a default and can be overridden by a CR.
