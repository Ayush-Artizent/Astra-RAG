"""Turns a plane's status fields into one line the model will actually read.

Both planes say useful things when something is wrong — an index that was never built, a symbol that
matched several definitions, a budget that cut content — but they say it in fields buried in a large
JSON payload, which a model skims. These build a short note to put in front of that payload. The
payload itself is never changed: the note is an extra, not a replacement.
"""
MAX_WARNINGS = 4
MAX_ALTERNATIVES = 3


def _symbols(resolved: list | None) -> list[str]:
    """Trouble resolving a name. The adapter refuses an ambiguous one, so results come back empty."""
    lines = []
    for item in resolved or []:
        if not isinstance(item, dict):
            continue
        name = item.get("input") or "a symbol"
        status = item.get("status")
        if status == "not_found":
            lines.append(f"'{name}' matched no symbol in this project.")
        elif status == "ambiguous":
            names = [a.get("qualified_name") for a in (item.get("alternatives") or [])
                     if isinstance(a, dict) and a.get("qualified_name")]
            shown = ", ".join(names[:MAX_ALTERNATIVES])
            lines.append(
                f"'{name}' matched several symbols, so it was refused"
                + (f" (for example {shown})" if shown else "")
                + ": ask again with a qualified name, or pin a file with path/to/file.py::Name."
            )
        elif status == "fuzzy":
            qualified = item.get("qualified_name")
            lines.append(f"'{name}' was matched loosely" + (f" to {qualified}" if qualified else "") + ".")
    return lines


def code_query(result: dict) -> str | None:
    """What to say about a code query before its payload."""
    parts: list[str] = []
    snapshot = result.get("snapshot") or {}
    status = result.get("plane_status")

    if status == "not_ready":
        state = snapshot.get("index_state")
        parts.append(
            "This project's code index is not ready"
            + (f" (state: {state})" if state else "")
            + ", so there are no code results yet. Documents are unaffected."
        )
    if snapshot.get("sync_in_progress"):
        parts.append("A sync is running, so source text and line numbers may not match the commit reported.")

    parts += _symbols(result.get("resolved_symbols"))

    if result.get("truncated"):
        parts.append("Results were cut at the limit: raise `limit` or narrow with `path_prefix`.")
    if status == "degraded" and not parts:
        parts.append("The code plane reported a degraded answer.")
    if status == "ok" and not parts and not result.get("results") and not result.get("flow"):
        parts.append("Nothing matched. Try keywords instead of a name, or check `code_index_status`.")
    return " ".join(parts) or None


def code_status(result: dict) -> str | None:
    parts: list[str] = []
    state = result.get("state")
    if state and state != "ready":
        parts.append(f"The code index is '{state}', so code queries will not answer fully yet.")
    if result.get("pruned_at"):
        parts.append("The project was deleted for being idle and is being rebuilt; it will answer again shortly.")
    lag = result.get("index_lag_seconds")
    if isinstance(lag, int) and lag > 0:
        parts.append(f"The index is about {lag // 60} minute(s) behind the repository." if lag >= 60
                     else "The index is seconds behind the repository.")
    if result.get("error"):
        parts.append(f"Last reported error: {result['error']}")
    return " ".join(parts) or None


def doc_context(result: dict) -> str | None:
    """Works for both document tools: one wraps its payload in `data`, the other does not."""
    inner = result.get("data")
    data = inner if isinstance(inner, dict) else result
    parts: list[str] = []

    if data.get("stale"):
        parts.append("Rules and template come from a cached copy: the repository host was unreachable.")

    status = data.get("status") or {}
    knowledge = str(status.get("knowledge") or "")
    if knowledge == "no_index":
        parts.append("The project data has not been indexed yet, so there is no evidence here; "
                     "any rules and template still are.")
    elif knowledge == "empty":
        parts.append("No project data matched.")
    elif knowledge.startswith("unavailable"):
        reason = knowledge.split(":", 1)[1].strip() if ":" in knowledge else "unavailable"
        parts.append(f"Searching the project data failed ({reason}), so evidence is missing from this answer.")
    if str(status.get("rerank") or "").startswith("skipped"):
        parts.append("Evidence is in search order: reranking was skipped.")

    for warning in (data.get("warnings") or [])[:MAX_WARNINGS]:
        message = warning.get("message") if isinstance(warning, dict) else None
        if message:
            parts.append(str(message))
    return " ".join(parts) or None
