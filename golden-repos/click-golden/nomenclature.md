# Nomenclature

Naming conventions for documents, identifiers and terms in the Click CLI Toolkit corpus.

## Document Naming

Documents use the pattern `CLK-<TYPE>-<NNN>-<slug>`, for example `CLK-CR-014-shell-completion`. Open: the final confirmed format for validate_document_name is still pending approval by the Documentation Lead.

## Type Codes

Type codes are BRD, TP, ADR, RN, CR, REQ, RAID. They map to business requirements document, test plan, architecture decision record, release notes, change request, requirement, and RAID log item.

## Requirement IDs

Requirement identifiers look like REQ-101. Non-functional requirements start at REQ-201.

## Jira Keys

Jira issues in the CLK project use keys CLK-1 to CLK-n. Pull requests are referenced as `PR-<number>` and map to upstream pull request numbers.

## Glossary

Command is a single callable CLI entry point (class `Command`). Group is a command that holds subcommands (class `Group`). Context is the per-invocation state object (class `Context`). Parameter is the base of Option and Argument. ParamType converts raw strings to typed values.

## Banned Terms

Do not write "MultiCommand" in new documents. It is the legacy name of `Group` and survives only as the deprecated `_MultiCommand` alias.
