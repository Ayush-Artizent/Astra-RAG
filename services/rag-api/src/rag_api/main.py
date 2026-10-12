from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rag_api import demo
from rag_api.deps import get_backends, get_settings
from rag_api.routers import tools
from rag_core.config import Environment
from rag_core.observability import configure_logging
from rag_core.schemas import INDEX_VERSION


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    # TODO(platform pod): azure-monitor-opentelemetry exporter when not local.
    if settings.env is Environment.LOCAL and settings.seed_demo_data:
        await demo.seed(get_backends())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Astra RAG API",
        version="0.1.0",
        description="Context retrieval for the Agentic SDLC platform. Every response carries "
        "citations, a trace_id and the repo->indexed_sha snapshot used to answer it.",
        lifespan=lifespan,
    )
    app.include_router(tools.router)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, object]:
        # TODO: check Postgres, search index and queue connectivity.
        return {"status": "ready", "index_version": INDEX_VERSION}

    return app


app = create_app()
