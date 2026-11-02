# Email: Removing Colorama

Date: 2026-04-10
From: Maintainer
To: Security Lead, Product Owner
Subject: Colorama removal plan

## Message

Supported Windows versions enable ANSI terminal styles by default, so Colorama is no longer needed. The runtime will then have zero third-party dependencies. This implements CR-015 and supersedes ADR-003.

## Impact

Console output on legacy Windows consoles without ANSI support will show raw escape codes. We accept this risk, tracked as RAID-R03.
