# CR-020 Built-in YAML config loading

Date: 2026-06-02
Owner: Platform Engineering Manager
Status: Rejected

## Description

Proposal to add built-in loading of option defaults from a YAML file.

## Decision

Rejected by the Product Owner on 2026-06-16. It would add a third-party dependency, which violates the dependency policy. Teams should use `Context.default_map` instead.
