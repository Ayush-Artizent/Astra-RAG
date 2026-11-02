# ADR-003 Use Colorama for Windows ANSI

Status: SUPERSEDED by ADR-007
Date: 2023-04-12
Owner: Maintainer

## Context

Older Windows consoles did not interpret ANSI escape codes.

## Decision

Depend on Colorama to translate ANSI styles on Windows. This decision is no longer in force.

## Consequences

The runtime had one third-party dependency on Windows.
