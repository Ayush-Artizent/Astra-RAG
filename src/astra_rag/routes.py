from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .config import REQUIRED_FILES, REQUIRED_FOLDERS, TEMPLATES_DIR
from .services import connections
from .services.errors import AppError
from .services.ingestion import pipeline
from .services.registry import repos, runs
from .services.registry.rules import check_project_id

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
def validate_and_clone(body: RepoRequest, background: BackgroundTasks):
    try:
        done = connections.connect(body.url, body.token, body.branch)
    except connections.MissingItemsError as exc:
        return JSONResponse({"ok": False, "missing": exc.missing, "token_saved": exc.token_saved,
                             "error": exc.message}, status_code=422)
    background.add_task(pipeline.run_ingestion, done.run_id, done.context, done.path)
    repo = done.context.ref
    return {
        "ok": True, "message": f"Cloned {repo.full_name}", "path": str(done.path),
        "branch": done.context.branch, "commit_sha": done.context.commit_sha,
        "token_saved": done.token_saved, "token_reused": not done.token_saved,
        "ingestion": {"slug": repo.slug, "run_id": done.run_id, "state": "queued"},
    }


@router.get("/api/ingestion-status/{slug}")
def ingestion_status(slug: str):
    status = runs.latest_run(slug)
    if status is None:
        raise AppError("No ingestion has been started for this repository.", 404)
    return {"ok": True, **status}


@router.get("/api/repos")
def list_repos():
    return {"ok": True, "repos": repos.list_repos()}


@router.put("/api/repos/{slug}/settings")
def repo_settings(slug: str, body: RepoSettings):
    return {"ok": True, "repo": connections.change_branch(slug, body.tracked_branch)}


@router.put("/api/projects/{project_id}/binding")
def bind_project(project_id: str, body: BindingRequest):
    return {"ok": True, "project": repos.bind_project(check_project_id(project_id), body.repo_slug)}


@router.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = repos.get_project(check_project_id(project_id))
    if project is None:
        raise AppError("This project is not bound to a repository.", 404)
    return {"ok": True, "project": project}


@router.post("/api/search")
def search(body: SearchRequest):
    hits = pipeline.search(body.slug, body.query, max(1, min(body.limit, 50)),
                           body.folder, body.file_type)
    return {"ok": True, "results": hits}
