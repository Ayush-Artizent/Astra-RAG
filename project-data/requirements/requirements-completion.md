# Completion Requirements

Date: 2026-03-08
Owner: Maintainer

## REQ-110 Shells

Completion must work for bash, zsh, fish and PowerShell.

## REQ-111 Activation

The completion script is generated when the environment variable `_<PROG>_COMPLETE` is set to `<shell>_source`, where PROG is the upper-cased program name with dashes replaced by underscores.

## REQ-112 Windows PowerShell 5.1

Open: whether Windows PowerShell 5.1 is mandatory or best effort is to decide.
