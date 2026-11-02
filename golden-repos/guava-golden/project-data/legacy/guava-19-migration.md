# Guava 19 to 32 Migration Notes

Date: 2025-07-22
Owner: Core Collections Lead

## Breaking items

Removed or changed between 19.0 and 32.x: Objects.firstNonNull replaced by MoreObjects.firstNonNull, Futures.transform requires an executor, CharMatcher constants replaced by factory methods.

## Outcome

63 repositories migrated; 58 completed by 2025-12-01. Open: the five remaining repositories belong to a decommissioned product and need a decision.
