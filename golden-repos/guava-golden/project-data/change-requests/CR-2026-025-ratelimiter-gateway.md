# Change Request CR-2026-025: Standard gateway RateLimiter configuration

Date: 2026-04-02
Owner: Platform Architect
Status: Approved on 2026-04-09

## Summary

Gateway services use RateLimiter.create(200.0) with a warm-up period of 3 seconds for cold downstream services.

## Impact

Applies to 14 gateway services. A smooth bursty limiter with default one second burst remains available for internal batch jobs.
