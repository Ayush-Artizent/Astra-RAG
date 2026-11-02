# RAID Log

Date: 2026-06-01
Owner: Program Manager

## Risks

R-004 Upstream breaking changes in Guava minor releases, medium, owner Core Collections Lead. R-007 Android flavor demand exceeds capacity, high, owner Mobile Platform Lead. R-009 Security review queue delay, medium, owner Security Architect.

## Assumptions

A-001 Guava continues to support JDK 8 in the jre flavor. A-002 Northwind support remains available through 2027-06-30.

## Issues

I-003 Flaky test in the ExecutionSequencer wrapper tracked as GPL-1042. I-005 Patch SLA mismatch between internal rule and vendor agreement.

## Dependencies

D-001 Internal Maven repository availability. D-002 Partner gateway retirement date to allow md5 allow-list removal.
