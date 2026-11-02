# ADR-007 Native ANSI on Windows

Status: Accepted (supersedes ADR-003)
Date: 2026-05-21
Owner: Maintainer

## Context

Supported Windows versions enable ANSI terminal styles by default.

## Decision

Remove Colorama. Styles are written as ANSI sequences, and `echo` strips them when the stream is not a terminal.

## Consequences

Zero runtime dependencies. Legacy consoles without ANSI show raw codes, tracked as RAID-R03.
