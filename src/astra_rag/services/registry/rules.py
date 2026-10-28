"""Input checks for registry values that reach git or the database."""
import re

from ...config import BRANCH_NAME_PATTERN, PROJECT_ID_PATTERN
from ..errors import AppError


def check_branch_name(name: str) -> str:
    name = (name or "").strip()
    if not re.fullmatch(BRANCH_NAME_PATTERN, name):
        raise AppError("Enter a valid branch name (letters, digits, '.', '_', '-' and '/'; "
                       "it must not start with '-').")
    return name


def check_project_id(project_id: str) -> str:
    if not re.fullmatch(PROJECT_ID_PATTERN, project_id or ""):
        raise AppError("A project id is 1-64 letters, digits, '.', '_' or '-'.", 422)
    return project_id
