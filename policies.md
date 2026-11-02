# Policies

Northwind Tooling treats Click as an internal product called the Click CLI Toolkit, maintained by the Developer Experience group. These policies apply to all documents about it.

## Data Handling

This section covers how Click CLI Toolkit documents are kept and classified.

### Retention

Project documents for the Click CLI Toolkit are retained for 5 years after the last release of a major version. Meeting notes and emails are retained for 2 years.

### Classification

All Click CLI Toolkit documents are classified Internal. Customer names never appear in them. Use role names such as Release Manager instead of personal names.

## Versioning

This section covers supported platforms and version numbering.

### Supported Python

The toolkit supports Python 3.10 and newer, matching `requires-python = ">=3.10"` in pyproject.toml. Dropping a Python minor version needs a change request and a Minor release.

### Semantic Versioning

Releases follow semantic versioning. Deprecations are announced in a Minor release and removal happens only in the next Major release. Click 9.0 is the planned removal point for names deprecated in the 8.x line.

## Deprecation

A deprecated name must emit a `DeprecationWarning` for at least one full Minor release before removal. The warning message must name the replacement.

## Security

This section covers dependencies and vulnerability handling.

### Dependency Policy

The runtime keeps zero mandatory third-party dependencies. Since 8.5.0 Colorama is no longer a dependency. Adding a runtime dependency requires an architecture decision record.

### Vulnerability Reporting

Vulnerabilities are reported privately to the Developer Experience security alias and triaged within 3 business days.

## Release Approval

A release needs approval from the Release Manager and one Maintainer. A Major release also needs the Product Owner.
