"""Central settings: what a repo must contain and where clones go."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_STORAGE_DIR = BASE_DIR / "temp_storage"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"

# Names must match exactly (case-sensitive) at the repository root.
REQUIRED_FILES = ("policies.md", "nomenclature.md")
REQUIRED_FOLDERS = ("project-data", "templates")

GIT_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 20
