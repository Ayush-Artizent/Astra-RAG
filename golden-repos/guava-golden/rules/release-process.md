# Release Process Rules

Owner: Release Manager. Date: 2026-03-02.

## Cadence

Rules for release timing.

### Release train

GPL ships one minor release per quarter and patch releases on demand. Release freeze starts 10 business days before the train date.

### Release candidates

Each minor release has at least one release candidate tagged vX.Y.Z-rc.N and soaked for 5 business days in the staging cluster.

## Approvals

Rules for approvals.

### Required sign-off

Release sign-off requires the Core Collections Lead, Security Architect, QA Lead and Release Manager. A missing sign-off blocks publication.

### Release notes

Release notes must list each change with its CR id, the affected package and the compatibility impact. Breaking changes are listed under a separate heading.

## Rollback

Rules for rollback.

### Rollback criteria

A release is rolled back if error rate of dependent services rises by more than 2 percent for 30 minutes. Rollback pins consumers to the prior acme suffix through guava-bom.
