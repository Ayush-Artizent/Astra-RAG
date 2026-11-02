# RAID Log: Risks and Issues

Date: 2026-08-01
Owner: Release Manager

## RAID-R03 Legacy console ANSI

Risk: raw escape codes on consoles without ANSI after Colorama removal. Severity medium. Mitigation: upgrade agents, see legacy-windows-consoles.

## RAID-R05 pytest 9.1

Risk: test failures with pytest 9.1 or newer. Mitigation: fixed in 8.5.0 (PR-3656). Status closed.

## RAID-I02 Help option name

Issue: a parameter named `help` clashed with the help option. Resolved by reserving `_click_default_help` in 8.6.0.
