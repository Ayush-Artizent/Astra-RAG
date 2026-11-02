# Meeting: Architecture Review

Date: 2026-05-21
Attendees: Maintainer, Platform Engineering Manager, Security Lead
Owner: Maintainer

## Decisions

ADR-007 accepted: rely on native ANSI support on Windows. The formatter width stays `max(min(terminal columns, max_width) - 2, 50)` with `max_width` defaulting to 80.

## Actions

Security Lead reviews the dependency-free runtime claim by 2026-06-04.

## Open Items

Open: whether `Parameter.human_readable_name` removal can move earlier than 9.0 is to decide.
