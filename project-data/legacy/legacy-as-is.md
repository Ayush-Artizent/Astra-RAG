# Legacy As-Is

Date: 2025-11-03
Owner: Platform Engineering Manager

## Pre-Click Scripts

About 60 internal tools were written with `optparse` and `argparse`. Migration to Click is incremental.

## Legacy Names

Older code uses `MultiCommand`, now the deprecated alias `_MultiCommand` of `Group`.

## Legacy Test Helper

Many old tests use `CliRunner.isolated_filesystem`, now deprecated. The `mix_stderr` parameter of CliRunner was removed.
