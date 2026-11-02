# Meeting: Testing Strategy

Date: 2026-07-09
Attendees: QA Lead, Maintainer, Release Manager
Owner: QA Lead

## Decisions

`CliRunner.isolated_filesystem` is deprecated because it relies on `os.chdir`, which is process-global and not thread-safe. Tests move to `tmp_path`. Parallel runs use pytest-xdist.

## Actions

QA Lead audits tests for isolated_filesystem usage by 2026-07-23.

## Open Items

Open: pytest 9.1 compatibility matrix needs an owner.
