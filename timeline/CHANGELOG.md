# Changelog (newest first)

## 2026-10-27
- Planning: W2 tool now also returns `nomenclature.md` (deterministic fetch, not RAG) and gains a nomenclature validator task; W1 noted as leaning Qdrant and scoped to `project-data/` only, pending further discussion.
- Added `timeline/` progress folder, `CLAUDE.md` project rules and the task breakdown (`TASKS.md`).

## 2026-10-26
- Switched project to `uv` (`uv.lock`, `.python-version`).
- Migrated to `src/astra_rag` layout with `uv_build` backend and `astra-rag` script.
- Added repo connector: URL parsing, GitHub root listing, mandatory-structure validation,
  token-safe shallow clone into `temp_storage/`, UI, and unit tests.

## 2026-10-12 / 2026-10-09
- Initial commit and refactor for readability (pre-connector scaffolding).
