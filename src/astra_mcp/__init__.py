"""ASTRA MCP server: the doc and code planes as MCP tools, over stdio.

Spawned once per client, so it keeps no database, no lock and no models of its own: it is an HTTP
client of the two planes. It must not import `astra_rag`, which would pull in FastAPI, the registry
and the sync worker on every spawn. See `plan/mcp-server-plan.md`.
"""
import sys

from .config import Config, ConfigError, load

__all__ = ["Config", "ConfigError", "load", "main"]


def main() -> None:
    """Entry point for `astra-mcp`. A configuration problem exits 2 with the reason on stderr."""
    try:
        config = load()
    except ConfigError as err:
        print(f"astra-mcp: {err}", file=sys.stderr)
        raise SystemExit(2) from None

    from .server import run  # imported late so a bad configuration fails before the SDK loads

    run(config)
