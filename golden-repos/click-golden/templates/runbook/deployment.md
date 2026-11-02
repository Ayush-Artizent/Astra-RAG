# Deployment Runbook

Variant of the runbook used for publishing a release.

## Preconditions

Green CI and approved release notes.

## Steps

Build, tag, upload to the internal package index, verify install.

## Rollback

Yank the version and pin consumers to the previous release.
