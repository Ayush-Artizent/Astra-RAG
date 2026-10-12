# ADR-0001: Monorepo with a uv workspace

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** platform pod
- **Design doc:** §3 (deployable units), §13 (team split)

## Context

There are four deployable units (`rag-ingest`, `rag-api`, `rag-mcp`, `rag-eval`), two shared
libraries (`rag-core`, `rag-parsers`) and an SDK. 6–10 engineers work in 4 pods and need to
ship an MVP in 4–6 weeks. The shared schemas (chunk, citation, trace) change often early on,
and every change crosses pods.

## Options considered

1. **Polyrepo with published internal packages.** Gives clean boundaries, but every schema change
   becomes a version bump plus N PRs. That is too slow for an MVP.
2. **Monorepo with a uv workspace.** One lockfile, atomic cross-package changes, one CI, and
   editable installs. Package boundaries are still explicit through each package's own `pyproject.toml`.

## Decision

Option 2. Each unit stays its own package with its own dependencies, so it can be extracted
later if needed. `deploy/docker/Dockerfile` builds a minimal image per unit with
`uv sync --package <unit>`.

## Consequences

- Cross-pod schema changes land in one PR, and CODEOWNERS routes review to the right pods.
- The import direction must stay acyclic: `rag-core` ← `rag-parsers` ← services. Services
  never import each other. The one exception is `rag-ingest`, which re-exports the redactor
  from `rag-core`.
- CI runs everything on every PR. Revisit with path filters if CI time exceeds about 10 minutes.
