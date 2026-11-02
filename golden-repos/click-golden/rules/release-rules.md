# Release Rules

Rules for cutting a release.

## Branching

Release branches are named in the `8.5.x` style. Fixes land on the release branch first and are merged forward.

## Changelog

Every pull request that changes behavior adds an entry to CHANGES.md with a `{pr}` reference. Entries for unreleased versions are marked Unreleased.

## Release Checklist

The Release Manager verifies green CI on every supported Python version, builds the sdist and wheel, and tags the release as `X.Y.Z`. Open: whether to sign tags with sigstore is to decide.
