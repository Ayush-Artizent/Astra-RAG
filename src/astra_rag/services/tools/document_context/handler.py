"""get_document_context: policies + nomenclature + matching template, read from GitHub."""
from concurrent.futures import ThreadPoolExecutor

from ....config import REQUIRED_FILES, TEMPLATE_ALIASES, TEMPLATE_EXTENSIONS, TEMPLATES_FOLDER
from ... import github_client
from ...errors import AppError
from ...github_client import RepoRef
from .schemas import DocumentContext, DocumentContextArgs, SourceRef

POLICIES_FILE, NOMENCLATURE_FILE = REQUIRED_FILES


def list_template_types(repo: RepoRef, token: str) -> dict[str, str]:
    """Discover {REQUEST_TYPE: filename} from templates/ on GitHub (409 if two files clash)."""
    types: dict[str, str] = {}
    for entry in github_client.list_dir(repo, TEMPLATES_FOLDER, token):
        name = entry["name"]
        if entry["type"] != "file" or not name.lower().endswith(TEMPLATE_EXTENSIONS):
            continue
        request_type = name.rsplit(".", 1)[0].upper()
        if request_type in types:
            raise AppError(
                f"Ambiguous template: '{types[request_type]}' and '{name}' both map to type {request_type}.", 409)
        types[request_type] = name
    return types


def add_type_enum(schema: dict, repo: RepoRef, token: str) -> None:
    """Schema hook: restrict `request_type` to the templates that exist in this repo."""
    types = list_template_types(repo, token)
    if types:
        schema["properties"]["request_type"]["enum"] = sorted(types)


def get_document_context(repo: RepoRef, token: str, args: DocumentContextArgs) -> DocumentContext:
    request_type = args.request_type.strip().upper()
    request_type = TEMPLATE_ALIASES.get(request_type, request_type)

    types = list_template_types(repo, token)
    if request_type not in types:
        valid = ", ".join(sorted(types)) or "none found"
        raise AppError(f"Unknown request type '{args.request_type}'. Valid types: {valid}.", 404)

    paths = [POLICIES_FILE, NOMENCLATURE_FILE, f"{TEMPLATES_FOLDER}/{types[request_type]}"]
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        policies, nomenclature, template = list(pool.map(lambda p: github_client.get_file(repo, p, token), paths))

    return DocumentContext(
        request_type=request_type,
        policies=policies["content"],
        nomenclature=nomenclature["content"],
        template=template["content"],
        sources=[SourceRef(path=f["path"], sha=f["sha"]) for f in (policies, nomenclature, template)],
    )
