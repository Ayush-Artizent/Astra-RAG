# Architecture Overview

Date: 2026-05-01
Owner: Maintainer

## Module Layout

Source lives in `src/click`: core.py (Context, Command, Group, CommandCollection, Parameter, Option, Argument), decorators.py, types.py, exceptions.py, formatting.py, parser.py, shell_completion.py, termui.py, testing.py and utils.py.

## Invocation Flow

A `Command` calls `make_context` to build a `Context`, parses arguments, then `invoke`. A `Group` resolves a subcommand with `resolve_command` and invokes it.

## Parameter Sources

`ParameterSource` is an IntEnum recording where a value came from, such as the command line, environment or default.
