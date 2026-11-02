# Functional Requirements

Date: 2026-02-25
Owner: Product Owner

## REQ-101 Nested commands

The toolkit must support arbitrary nesting of commands through `Group` and `Command`, with lazy loading of subcommands via `Group.get_command` and `list_commands`.

## REQ-102 Parameter types

Built-in ParamTypes must include Choice, IntRange, FloatRange, DateTime, File, Path, Tuple and UUID.

## REQ-103 Error exit codes

A `UsageError` exits with code 2. A generic `ClickException` exits with code 1.

## REQ-104 Help width (SUPERSEDED)

Status: SUPERSEDED by REQ-109. Help output wraps at a fixed width of 80 columns.

## REQ-109 Help width

Help width is `max(min(terminal columns, max_width) - 2, 50)`, where `max_width` defaults to 80 and can be set with `Context.max_content_width`.
