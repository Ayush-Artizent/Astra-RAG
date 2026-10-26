from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .config import REQUIRED_FILES, REQUIRED_FOLDERS, TEMPLATES_DIR
from .services import cloner, github_client, validator
from .services.errors import AppError

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class RepoRequest(BaseModel):
    url: str = ""
    token: str = ""


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html",
        {"required_files": REQUIRED_FILES, "required_folders": REQUIRED_FOLDERS},
    )


# Plain `def` so FastAPI runs these blocking network/git calls in a worker thread.
@router.post("/api/validate-and-clone")
def validate_and_clone(body: RepoRequest):
    token = body.token.strip()
    if not token:
        raise AppError("A personal access token is required.")

    repo = github_client.parse_repo_url(body.url)
    missing = validator.find_missing(github_client.list_root(repo, token))
    if missing:
        return JSONResponse(
            {"ok": False, "missing": missing,
             "error": "Repository is missing required items: " + ", ".join(missing)},
            status_code=422,
        )

    path = cloner.clone_repo(repo, token)
    return {"ok": True, "message": f"Cloned {repo.owner}/{repo.name}", "path": path}
