from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .config import REQUIRED_FILES, REQUIRED_FOLDERS, TEMPLATES_DIR
from .services import connections, sync
from .services.catalog import service as catalog_service
from .services.context import service as context_service
from .services.errors import AppError
from .services.ingestion import pipeline
from .services.registry import repos, runs
from .services.registry.rules import check_project_id
from .services.sync import scheduler

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class RepoRequest(BaseModel):
    url: str = ""
    token: str = ""
    branch: str = ""  # blank = the saved tracked branch, else the host's default branch


class RepoSettings(BaseModel):
    tracked_branch: str


class BindingRequest(BaseModel):
    repo_slug: str


class ContextRequest(BaseModel):
    project_id: str
    doc_type: str
    stage: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)


class SearchRequest(BaseModel):
    slug: str
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


# Plain `def` so FastAPI runs these blocking network/git/SQLite calls in a worker thread.
@router.post("/api/validate-and-clone")
def validate_and_clone(body: RepoRequest):
    try:
        done = connections.connect(body.url, body.token, body.branch)
    except connections.MissingItemsError as exc:
        return JSONResponse({"ok": False, "missing": exc.missing, "token_saved": exc.token_saved,
                             "error": exc.message}, status_code=422)
    repo = done.context.ref
    if done.run_id is None:
        state, message = "pending", f"Connected {repo.full_name}; a sync is running, so another one follows it."
    else:
        sync.start(done.run_id)
        state, message = "queued", f"Connected {repo.full_name}; sync queued."
    return {
        "ok": True, "message": message, "branch": done.context.branch, "commit_sha": done.context.commit_sha,
        "token_saved": done.token_saved, "token_reused": not done.token_saved,
        "ingestion": {"slug": repo.slug, "run_id": done.run_id, "state": state},
    }


@router.get("/api/ingestion-status/{slug}")
def ingestion_status(slug: str):
    status = runs.latest_run(slug)
    if status is None:
        raise AppError("No ingestion has been started for this repository.", 404)
    return {"ok": True, **status}


@router.get("/api/repos")
def list_repos():
    return {"ok": True, "repos": repos.list_repos(), "schedule": scheduler.schedule()}


@router.put("/api/repos/{slug}/settings")
def repo_settings(slug: str, body: RepoSettings):
    return {"ok": True, "repo": connections.change_branch(slug, body.tracked_branch)}


@router.post("/api/repos/{slug}/sync")
def sync_now(slug: str):
    return {"ok": True, "slug": slug, **sync.request_sync(slug, "manual")}


@router.put("/api/projects/{project_id}/binding")
def bind_project(project_id: str, body: BindingRequest):
    return {"ok": True, "project": repos.bind_project(check_project_id(project_id), body.repo_slug)}


@router.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = repos.get_project(check_project_id(project_id))
    if project is None:
        raise AppError("This project is not bound to a repository.", 404)
    return {"ok": True, "project": project}


@router.get("/api/projects/{project_id}/catalog")
def project_catalog(project_id: str, include_text: bool = False):
    repo, catalog = catalog_service.catalog_for_project(project_id)
    return {"ok": True, "project_id": project_id, "repo": repo["slug"], "branch": repo["tracked_branch"],
            **catalog.to_dict(include_text)}


@router.get("/api/repos/{slug}/catalog")
def repo_catalog(slug: str, include_text: bool = False):
    repo, catalog = catalog_service.catalog_for_repo(slug)
    return {"ok": True, "repo": repo["slug"], "branch": repo["tracked_branch"], **catalog.to_dict(include_text)}


@router.post("/api/context/preview")
def context_preview(body: ContextRequest):
    return {"ok": True, "project_id": body.project_id,
            **context_service.preview(body.project_id, body.doc_type, body.stage, body.tags)}


@router.post("/api/search")
def search(body: SearchRequest):
    hits = pipeline.search(body.slug, body.query, max(1, min(body.limit, 50)),
                           body.folder, body.file_type)
    return {"ok": True, "results": hits}
