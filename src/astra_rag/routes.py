from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .config import REQUIRED_FILES, REQUIRED_FOLDERS, TEMPLATES_DIR
from .services import cloner, github_client, token_store, validator
from .services.errors import AppError
from .services.ingestion import pipeline
from .services.ingestion.models import RepoContext
from .services.tools import registry

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class RepoRequest(BaseModel):
    url: str = ""
    token: str = ""


class ToolInvokeRequest(BaseModel):
    name: str
    arguments: dict = {}


class SearchRequest(BaseModel):
    owner: str
    name: str
    query: str
    limit: int = 8
    folder: str | None = None
    file_type: str | None = None


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html",
        {"required_files": REQUIRED_FILES, "required_folders": REQUIRED_FOLDERS},
    )


# Plain `def` so FastAPI runs these blocking network/git calls in a worker thread.
@router.post("/api/validate-and-clone")
def validate_and_clone(body: RepoRequest, background: BackgroundTasks):
    repo = github_client.parse_repo_url(body.url)
    typed = body.token.strip()
    token = typed or token_store.get_token(repo)
    if not token:
        raise AppError("A personal access token is required (none is saved for this repository).")

    missing = validator.find_missing(github_client.list_root(repo, token))
    if missing:
        return JSONResponse(
            {"ok": False, "missing": missing,
             "error": "Repository is missing required items: " + ", ".join(missing)},
            status_code=422,
        )

    clone = cloner.clone_repo(repo, token)
    if typed:  # only a token that just worked is remembered
        token_store.save(repo, body.url, typed)
    context = RepoContext(repo.host, repo.owner, repo.name, clone.branch, clone.commit_sha)
    pipeline.mark_queued(context)
    background.add_task(pipeline.run_ingestion, context, Path(clone.path))
    return {
        "ok": True, "message": f"Cloned {repo.owner}/{repo.name}", "path": clone.path,
        "commit_sha": clone.commit_sha,
        "token_saved": bool(typed), "token_reused": not typed,
        "ingestion": {"owner": repo.owner, "name": repo.name, "state": "queued"},
    }


@router.get("/api/ingestion-status/{owner}/{name}")
def ingestion_status(owner: str, name: str):
    status = pipeline.get_status(owner, name)
    if status is None:
        raise AppError("No ingestion has been started for this repository.", 404)
    return {"ok": True, **status}


@router.post("/api/search")
def search(body: SearchRequest):
    hits = pipeline.search(body.owner, body.name, body.query, max(1, min(body.limit, 50)),
                           body.folder, body.file_type)
    return {"ok": True, "results": hits}


@router.get("/api/tools")
def list_tools(owner: str | None = None, name: str | None = None):
    """Tool schemas; pass owner + name to also add live hints (e.g. valid request types) for that repo."""
    creds = token_store.get_credentials(owner, name) if owner and name else None
    return {"ok": True, "tools": registry.describe_tools(creds)}


@router.post("/api/tools/invoke")
def invoke_tool(body: ToolInvokeRequest):
    return {"ok": True, "result": registry.run_tool(body.name, body.arguments)}
