# API Compatibility Rules

Rules for compatibility with upstream Guava and with downstream consumers. Owner: Platform Architect. Date: 2026-02-10.

## Beta APIs

Rules for APIs annotated Beta upstream.

### Use of Beta

Beta APIs may not be used in public GPL APIs. They may be used internally with an ADR recording the risk. Open: whether Beta APIs promoted to stable in 33.x are automatically allowed is to decide.

### Tracking

The Platform Architect keeps the Beta usage inventory in architecture/beta-usage-inventory.md and refreshes it each minor release.

## Binary compatibility

Rules for binary compatibility.

### Compatibility rule

GPL minor releases must be binary compatible with the previous minor release. The japicmp check runs in CI and fails the build on any incompatible change in com.acme.platform.guava packages.

### Upstream upgrades

Upstream Guava upgrades are applied only after the compatibility report is attached to the change request. Major jumps need an ADR.

## Flavors

Rules for flavors.

### Dual publishing

Every release publishes both jre and android flavors from the same tag. A release is blocked if only one flavor passes the test suite.
