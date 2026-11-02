# Coding Standards

Rules for source code in the toolkit.

## Typing

All public functions carry full type annotations and the package ships `py.typed`. Type checking runs in CI with mypy and pyright.

## Naming

Parameter names must be valid lower-case Python identifiers. From 8.6.0 a name that is not a valid identifier, or is a keyword, is deprecated and raises `TypeError` in 9.0.

## Output

Use `click.echo` instead of `print` so that output is stream safe and ANSI codes are stripped when the stream is not a terminal.
