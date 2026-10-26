"""Central settings: what a repo must contain and where clones go."""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
BASE_DIR = PACKAGE_DIR.parent.parent  # repo root
TEMP_STORAGE_DIR = BASE_DIR / "temp_storage"
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# Names must match exactly (case-sensitive) at the repository root.
REQUIRED_FILES = ("policies.md", "nomenclature.md")
REQUIRED_FOLDERS = ("project-data", "templates")

GIT_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 20
