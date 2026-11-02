# Beta API Usage Inventory

Date: 2026-06-30
Owner: Platform Architect
Status: Approved

## Inventory

Internal use of Beta APIs: ClosingFuture in util.concurrent (2 services), RangeSet extensions in collect (1 service) and LittleEndianByteArray indirectly via hash. No Beta type is exposed in public GPL APIs.

## Follow-up

Open: ClosingFuture usage in the reporting service needs an ADR.
