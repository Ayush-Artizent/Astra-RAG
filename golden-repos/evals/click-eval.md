# Click golden repo eval

Source corpus: golden-repos/click-golden. Categories: factual, conflict/superseded, open-item, rule-selection, code-plus-golden, negative.

| # | Category | Question | Expected answer | Source |
|---|----------|----------|-----------------|--------|
| 1 | factual | What is the minimum supported Python version? | 3.10 (`requires-python >=3.10`) | policies.md#versioning/supported-python; REQ-201 |
| 2 | factual | When was 8.5.0 released? | 2026-08-24 | emails/2026-08-30-release-announcement.md |
| 3 | factual | Which shells have built-in completion in 8.5.0? | bash, zsh, fish, PowerShell | requirements-completion.md REQ-110 |
| 4 | factual | How is a PowerShell completion script generated? | `_FOO_BAR_COMPLETE=powershell_source foo-bar` style env var | emails/2026-03-02-completion-scope.md; REQ-111 |
| 5 | factual | What exit code does a UsageError produce? | 2 (ClickException is 1) | requirements-functional.md REQ-103 |
| 6 | factual | What is the line coverage threshold? | 95 percent for src/click | REQ-203; rules/testing-rules.md#coverage |
| 7 | factual | Which jira issue covers Parameter.spec and what is its status/fix version? | CLK-107, In Progress, 8.6.0 | jira-export/jira-issues.csv row CLK-107 |
| 8 | factual | How many invocations did lint have in 2026-09? | 24100 (metric M007) | analytics/command-usage.csv |
| 9 | factual | When does the docs hosting contract end? | 2027-01-31 | contracts/CTR-001-docs-hosting.md |
| 10 | factual | What licence does the upstream package use? | BSD-3-Clause | compliance/license-compliance.md |
| 11 | factual | What was CR-020 and its outcome? | Built-in YAML config loading, rejected 2026-06-16 (new dependency); use Context.default_map | change-requests/CR-020-yaml-config-loading.md |
| 12 | conflict/superseded | Does help output wrap at a fixed 80 columns? | No. REQ-104 is superseded by REQ-109: max(min(terminal columns, max_width) - 2, 50), max_width default 80 | requirements-functional.md REQ-104/REQ-109 |
| 13 | conflict/superseded | Does the toolkit depend on Colorama? | No. ADR-003 is superseded by ADR-007; removed in 8.5.0 | architecture/ADR-003, ADR-007 |
| 14 | conflict/superseded | Which ADR currently governs Windows ANSI handling? | ADR-007 (accepted 2026-05-21) | architecture/ADR-007-native-ansi.md |
| 15 | conflict/superseded | Is CliRunner.isolated_filesystem recommended for new tests? | No, deprecated in 8.6.0 (CR-016); use tmp_path | rules/testing-rules.md#runner-usage; CR-016 |
| 16 | open-item | What is the final nomenclature format for document-name validation? | Unconfirmed; pending Documentation Lead approval | nomenclature.md#document-naming |
| 17 | open-item | Is Windows PowerShell 5.1 mandatory for completion? | Undecided; Maintainer to answer (by 2026-03-13) | emails/2026-03-02-completion-scope.md; REQ-112 |
| 18 | open-item | What is the 8.6.0 release date? | Not fixed; to decide | meeting-notes/2026-09-17-planning-8-6.md |
| 19 | open-item | Is the docs hosting contract renewal decided? | No, decision due by 2026-11-30 | CTR-001; RAID-D02 |
| 20 | open-item | Should release tags be signed with sigstore? | To decide | rules/release-rules.md#release-checklist |
| 21 | rule-selection | Which rule sections are always selected for any request? | nomenclature.md (all), policies.md data-handling, rules/doc-writing.md | golden.yaml |
| 22 | rule-selection | Which rules apply to a RELEASE-NOTES document in review stage? | Always rules plus versioning, release-approval, rules/release-rules.md | golden.yaml |
| 23 | rule-selection | Which rules apply to a TEST-PLAN? | Always rules plus rules/testing-rules.md (priority 50) | golden.yaml |
| 24 | rule-selection | Which doc type has multiple template variants and what is the default? | RUNBOOK: incident, deployment, onboarding; default incident | golden.yaml; templates/runbook |
| 25 | code-plus-golden | Which class implements PowerShell completion and which base class does it extend, and which CR introduced it? | PowerShellComplete extends ShellComplete in shell_completion.py; CR-014 | CR-014; src/click/shell_completion.py |
| 26 | code-plus-golden | The ADR says width is max_width default 80; where in code is that default set? | src/click/formatting.py HelpFormatter: max_width None becomes 80; width = max(min(columns, max_width) - 2, 50) | ADR/meeting 2026-05-21; formatting.py |
| 27 | code-plus-golden | What reserved name does the automatic help option use after RAID-I02? | `_click_default_help` | raid-risks.md RAID-I02; core.py |
| 28 | negative | What is the GraphQL plugin API of the toolkit? | Not in corpus | none |
| 29 | negative | Who is the named CEO of Northwind Tooling? | Not in corpus | none |
| 30 | negative | What is the 9.0 release date? | Not in corpus; only that deprecated names are removed in 9.0 | none |
