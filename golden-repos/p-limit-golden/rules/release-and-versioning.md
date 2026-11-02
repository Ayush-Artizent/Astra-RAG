# Release Rules

Rules for publishing LimitKit versions.

## Release process

Gates and cadence for normal releases.

### Release gates

A release needs a green `npm test`, an updated changelog entry, and sign-off from the release manager.

### Release cadence

Minor releases ship at most once per month. Patch releases can ship any time after the gates pass.

## Hotfix handling

When an out-of-cycle release is allowed.

### Hotfix criteria

A hotfix is allowed only for defects that cause deadlock, lost tasks, or unhandled rejections in production use. Hotfixes use the hotfix release-notes variant.

## Deprecation

How features are retired.

### Deprecation window

A feature is deprecated for at least one minor release before removal in the next major release.
