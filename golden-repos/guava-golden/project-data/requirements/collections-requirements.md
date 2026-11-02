# Collections Requirements

Date: 2026-01-22
Owner: Core Collections Lead
Status: Approved

## REQ-COL-001 immutable returns

Public APIs of platform modules shall return ImmutableList, ImmutableSet, ImmutableMap or ImmutableMultimap.

## REQ-COL-002 multimap helper

The platform shall provide a PlatformMultimaps helper in com.acme.platform.guava.collect that wraps MultimapBuilder with approved backing types.

## REQ-COL-003 range sets

Scheduling services shall use RangeSet and RangeMap from com.google.common.collect for non-overlapping time windows.

## REQ-COL-004 ordering

Sorting utilities shall use Ordering or Comparator.comparing; Ordering is permitted but not preferred in new code. Open: formal deprecation of Ordering is to decide.
