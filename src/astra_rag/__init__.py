from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import PACKAGE_DIR, STATIC_DIR
from .routes import router
from .services.errors import AppError


def create_app() -> FastAPI:
    app = FastAPI(title="Astra RAG – Repository Connector")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, err: AppError):
        return JSONResponse({"ok": False, "error": err.message}, status_code=err.status)

    return app


def main() -> None:
    """Entry point for `uv run astra-rag`."""
    import uvicorn

    uvicorn.run(
        "astra_rag:create_app", factory=True, host="127.0.0.1", port=5000,
        reload=True,
        reload_dirs=[str(PACKAGE_DIR)],
    )
