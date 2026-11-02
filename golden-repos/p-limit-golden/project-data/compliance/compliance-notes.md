# Compliance Notes

Date: 2026-02-20
Owner: Security and Compliance Officer

## License

The package is MIT licensed. The license file must ship with every published artifact.

## Dependency scanning

Weekly scans cover `yocto-queue` and all dev dependencies. Findings of severity high must be fixed within 14 days.

## Data protection

The library stores no data and makes no network calls. It is out of scope for privacy impact assessments.

## Open items

Open: confirm whether the software bill of materials must list dev dependencies.
