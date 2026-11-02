# Email: Shell completion scope

Date: 2026-03-02
From: Product Owner
To: Maintainer, QA Lead
Subject: Shell completion scope for 8.5

## Message

We want built-in completion for bash, zsh and fish plus PowerShell in the 8.5.0 release. Completion scripts are generated through the environment variable pattern `_FOO_BAR_COMPLETE=powershell_source foo-bar`. See CR-014.

## Questions

Open: should Windows PowerShell 5.1 be a hard requirement or best effort alongside pwsh 7+? The Maintainer should answer by 2026-03-13.
