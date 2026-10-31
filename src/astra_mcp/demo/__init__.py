"""The demo page: a real MCP client with a web front end, for showing the connector working.

Not for production. It is a separate FastAPI app because the MCP server is stdio and spawned per
client, so there is nothing to attach a page to. See `plan/console-plan.md`.

`astra_mcp/__init__.py` never imports this, so the MCP server itself stays import-light.
"""
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import Config, ConfigError, load
from .paths import STATIC_DIR
from .routes import router
from .session import McpSession

DEFAULT_PORT = 5050

# What the operating system needs to start a Python process at all; everything else the child is
# told comes from the configuration below.
INHERITED = ("SYSTEMROOT", "PATH", "PATHEXT", "TEMP", "TMP")


def server_env(config: Config) -> dict:
    """The child's environment, built from this page's own configuration.

    Taken from the `Config` rather than from `os.environ`, so the page and the server it spawns
    cannot disagree about which project is being shown or which planes to call.
    """
    env = {name: os.environ[name] for name in INHERITED if name in os.environ}
    env.update({
        "ASTRA_ORG_ID": config.org_id,
        "ASTRA_PROJECT_ID": config.project_id,
        "ASTRA_ENVELOPE_KEY": config.envelope_key,
        "ASTRA_DOC_URL": config.doc_url,
        "ASTRA_CODE_URL": config.code_url,
        "ASTRA_MCP_TIMEOUT_MS": str(config.timeout_ms),
    })
    return env


def create_app(config: Config | None = None, session: McpSession | None = None) -> FastAPI:
    config = config or load()
    mcp = session or McpSession(server_env(config), timeout=config.timeout_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        mcp.stop()  # never leave the spawned server behind

    app = FastAPI(title="ASTRA MCP demo", lifespan=lifespan)
    app.state.config = config
    app.state.session = mcp
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    return app


def main() -> None:
    """Entry point for `astra-mcp-demo`."""
    try:
        config = load()
    except ConfigError as err:
        print(f"astra-mcp-demo: {err}", file=sys.stderr)
        raise SystemExit(2) from None
    import uvicorn

    port = int(os.environ.get("ASTRA_DEMO_PORT") or DEFAULT_PORT)
    print(f"astra-mcp-demo: http://127.0.0.1:{port}  (project {config.project_id})", file=sys.stderr)
    uvicorn.run(create_app(config), host="127.0.0.1", port=port, log_level="warning")
