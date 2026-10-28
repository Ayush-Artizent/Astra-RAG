from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import PACKAGE_DIR, STATIC_DIR, SYNC_SCHEDULER_ENABLED
from .routes import router
from .services import registry
from .services.errors import AppError
from .services.sync import reconcile, scheduler, worker
from .services.sync.instance import InstanceLock


@asynccontextmanager
async def lifespan(_: FastAPI):
    lock = InstanceLock()
    lock.acquire()  # one instance per data directory; everything below assumes it owns the runs
    try:
        registry.startup()  # refuses to start on a database newer than this code
        if SYNC_SCHEDULER_ENABLED:
            reconcile.run()
        worker.start()
        if SYNC_SCHEDULER_ENABLED:
            scheduler.start()
        yield
    finally:
        scheduler.stop()
        worker.stop()
        lock.release()


def create_app() -> FastAPI:
    app = FastAPI(title="Astra RAG – Repository Connector", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, err: AppError):
        return JSONResponse({"ok": False, "error": err.message}, status_code=err.status)

    return app


def main() -> None:
    """Entry point for `uv run python -m astra_rag`."""
    import uvicorn

    uvicorn.run(
        "astra_rag:create_app", factory=True, host="127.0.0.1", port=5000,
        reload=True,
        reload_dirs=[str(PACKAGE_DIR)],
    )
