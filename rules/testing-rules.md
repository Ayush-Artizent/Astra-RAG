# Testing Rules

Rules for tests of the toolkit.

## Runner Usage

Tests use `CliRunner.invoke` to drive commands. Do not use `CliRunner.isolated_filesystem` in new tests because it is deprecated in 8.6.0; use pytest `tmp_path` with absolute paths.

## Coverage

Line coverage must stay at or above 95 percent for `src/click`. New code needs tests in the matching file, for example `tests/test_options.py` for Option changes.

## Parallelism

Parallel runs use process isolation such as pytest-xdist, never threads, since CliRunner redirects process-global streams.
