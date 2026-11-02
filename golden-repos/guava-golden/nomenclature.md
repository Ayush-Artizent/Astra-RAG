# Naming Conventions

Naming rules for documents, artifacts and identifiers in the GPL program. Owner: Documentation Lead. Date: 2026-01-20. Open: this format is still unconfirmed and document-name validation is blocked on it.

## Document names

How documents are named.

### Pattern

Document names follow GPL-TYPE-NNN-short-title where TYPE is the uppercase type code, NNN is a three digit sequence and short-title is kebab-case. Example: GPL-ADR-014-cache-default-sizing. Release notes use GPL-RN-version, for example GPL-RN-33.7.2-acme.3.

### Type codes

Type codes: BRD, TP (test plan), ADR, RN (release notes), CR (change request), RB (runbook), DS (design spec), RFC. Meeting notes use MN and emails use EM only in the project-data folders.

## Identifiers

How identifiers are formed.

### Requirement ids

Requirements use REQ-AREA-NNN where AREA is one of COL, CACHE, BASE, HASH, CONC, IO, SEC, DOC. Example: REQ-CACHE-004.

### Change request ids

Change requests use CR-YYYY-NNN, for example CR-2026-017. Emergency changes add the suffix -E.

### Risk and issue ids

RAID items use R-NNN for risks, A-NNN for assumptions, I-NNN for issues and D-NNN for dependencies or decisions.

## Versioning

How versions are written.

### Artifact versions

GPL versions mirror the upstream Guava version plus an internal suffix: 33.7.2-jre-acme.N for the JRE flavor and 33.7.2-android-acme.N for the Android flavor. N starts at 1 for every upstream version.

### Package naming

Internal extension code lives under com.acme.platform.guava and must never be placed in com.google.common packages.
