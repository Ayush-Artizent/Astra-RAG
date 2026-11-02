# CR-016 Deprecate isolated_filesystem

Date: 2026-07-14
Owner: QA Lead
Status: Approved

## Description

Deprecate `CliRunner.isolated_filesystem`. It uses `os.chdir`, which mutates process-global state. Replacement: `tempfile.TemporaryDirectory` or pytest `tmp_path`.

## Approval

Approved by the Maintainer on 2026-07-20. Targets 8.6.0 (PR-3704). Removal planned for 9.0.
