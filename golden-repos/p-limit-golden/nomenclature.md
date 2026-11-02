# Nomenclature

Names and identifier formats used across LimitKit documents.

## Product names

How the product and package are named.

### Names in use

The product is called LimitKit internally. The npm package and import name is `p-limit`. Use LimitKit in prose and `p-limit` in code and install commands.

### Glossary of terms

A limiter is the function returned by `pLimit(concurrency)`. A task is a promise-returning or async function passed to a limiter. Active means running; pending means queued and not yet started.

## Identifiers

Formats for identifiers used in project records.

### Change request ids

Change requests use `CR-NNN`, a three digit sequence, for example CR-101.

### Requirement ids

Requirements use `REQ-NNN`. Non-functional requirements use `NFR-NNN`. Risks in the RAID log use `R-NNN`, issues `I-NNN`, assumptions `A-NNN`, dependencies `D-NNN`.

### Jira keys

Jira issues use project key `LIM`, for example LIM-214.

## Document naming

How project documents are named.

### Document file names

Open: the final document naming format is not confirmed. Interim convention is `<DOCTYPE>-<short-title>-<YYYY-MM-DD>.md`, to decide with the documentation lead.
