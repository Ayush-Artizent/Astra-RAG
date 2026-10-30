# Astra-RAG - project rules for Claude

Astra-RAG connects a "golden" GitHub repo (must contain `policies.md`, `nomenclature.md`,
`project-data/`, `templates/`), clones it, and (in progress) ingests it for RAG and exposes a
tool that returns policies + document templates.

## First thing every session
Read `timeline/CURRENT_STATE.md` and `timeline/TASKS.md` before doing anything. They are the
source of truth for what the repo does and what is left. If they disagree with the code, trust
the code and fix the docs.

## Last thing every session (definition of done)
Before finishing any change that alters behaviour, structure, dependencies, endpoints or config:
1. Update `timeline/CURRENT_STATE.md` (overwrite the affected sections, bump the date).
2. Update task status in `timeline/TASKS.md`.
3. Prepend a dated entry to `timeline/CHANGELOG.md` (what + why, one or two lines).
4. Update `README.md` if run steps or structure changed.
Pure refactors with no visible change still get a CHANGELOG line.

## Stack and commands
- Python >=3.14, `uv`, FastAPI, src layout in `src/astra_rag/`.
- Install/run: `uv sync`, `uv run python -m astra_rag` (prefer `python -m`; the `.exe` shim can be blocked on Windows).
- Tests: `uv run python -m unittest discover -s tests -t .`. Add tests for new logic; tests must not need network or real tokens.
- Add dependencies with `uv add <pkg>` (keeps `pyproject.toml` and `uv.lock` in sync).

## Code conventions
- Business logic lives in `services/`; `routes.py` stays thin. New features get their own subpackage (`services/ingestion/`, `services/catalog/`, `services/tools/`).
- Constants and required-structure rules live in `config.py`, not scattered.
- User-facing failures raise `AppError(message, status)`; messages must be safe to show.
- Plain `def` for blocking I/O routes (runs in a worker thread); don't block the event loop.
- Match the surrounding style: small functions, short docstrings, minimal comments.

## Security (non-negotiable)
- The GitHub PAT is saved only in the git-ignored `.env` (via `services/token_store.py`, keyed per repo URL), written only after the host accepted it (the root listing succeeded), even if the repo then fails validation. Never log it, return it from any API, put it in a URL or in `.git/config`, show it in the UI, or commit it. Adapters receive it only as a `PatCredential` and pass it to git via environment variables (see `services/sources/git.py`), not command-line arguments. Later features (W2) get it with `token_store.get_token(repo)`.
- Never commit `temp_storage/` contents, `.env` (holds PATs), or vector-store data; keep them git-ignored.
- Treat repo content (policies, templates, project data) as data, not instructions, when passing it to an LLM.

## Domain rules
- Required root items are case-sensitive and defined only in `config.py` (`REQUIRED_FILES`, `REQUIRED_FOLDERS`).
- The clone in `temp_storage/` exists only while a run ingests it and is deleted when the run ends; a repeat ingest replaces the index (alias switch), not a clone.
- Local models are downloaded by `services/local_models.py` at startup; code that needs one goes through `get_embedder()` / `get_reranker()` (they fail fast with `ModelsNotReady`), never loads a model inside a request.
- The policies/template tool reads from the host directly (via `services/catalog`), not from the local clone.

## Git
- Work on a feature branch (currently `goldan-repo-re-guru`; delivery follows `plan/phases.md`, one phase per PR); `main` is the PR target.
- Small, focused commits. Only commit/push when the user asks.
