"""Central settings: what a repo must contain and where clones go."""
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
BASE_DIR = PACKAGE_DIR.parent.parent  # repo root
TEMP_STORAGE_DIR = BASE_DIR / "temp_storage"
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# Names must match exactly (case-sensitive) at the repository root.
REQUIRED_FILES = ("policies.md", "nomenclature.md")
REQUIRED_FOLDERS = ("project-data", "templates")

# Golden catalog: rules and templates read from the repo outside project-data/ (see services/catalog).
GOLDEN_MANIFEST_NAME = "golden.yaml"
RULE_FILES = ("policies.md", "nomenclature.md")
RULES_FOLDER = "rules"  # optional: extra rule files, `rules/**.md`
TEMPLATES_FOLDER = "templates"
MAX_CATALOG_FILE_BYTES = 1024 * 1024
DEFAULT_RULE_PRIORITY = 100

# Host kinds a repo URL may point at today (see services/repo_ref.host_kind).
SUPPORTED_HOST_KINDS = ("github", "ghe", "azure_devops")

GIT_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 20

# --- Registry (repos, project bindings, ingestion runs) ------------------
DB_PATH = Path(os.environ.get("ASTRA_DB_PATH") or BASE_DIR / "data" / "astra.db")  # git-ignored
DB_BUSY_TIMEOUT_SECONDS = 5
# A strict subset of git's ref-name rules; it also stops a name from being read as a git option.
BRANCH_NAME_PATTERN = r"(?![-/.])(?!.*(?:\.\.|//|/\.))(?!.*(?:/|\.|\.lock)$)[A-Za-z0-9._/-]{1,200}"
PROJECT_ID_PATTERN = r"[A-Za-z0-9._-]{1,64}"

# --- RAG ingestion -------------------------------------------------------
PROJECT_DATA_DIR_NAME = "project-data"
CACHE_DIR = BASE_DIR / ".cache"
FASTEMBED_CACHE_DIR = Path(os.environ.get("FASTEMBED_CACHE_DIR", CACHE_DIR / "fastembed"))

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
QDRANT_COLLECTION_PREFIX = "astra"

DENSE_MODEL = "BAAI/bge-base-en-v1.5"
DENSE_DIM = 768
SPARSE_MODEL = "Qdrant/bm25"
EMBED_BATCH_SIZE = 32

# bge accepts at most 512 tokens; stay below so nothing is silently truncated.
CHUNK_TARGET_TOKENS = 380
CHUNK_MAX_TOKENS = 480
CHUNK_MIN_TOKENS = 100
CHUNK_OVERLAP_TOKENS = 50

# project-data folder name -> doc_type stored on every chunk (unknown folders keep their own name)
DOC_TYPE_BY_FOLDER = {
    "emails": "email", "meeting-notes": "meeting-note", "change-requests": "change-request",
    "requirements": "requirement", "stakeholders": "stakeholder-register", "contracts": "contract",
    "charter": "charter", "architecture": "architecture", "compliance": "compliance", "legacy": "as-is",
    "ux": "ux", "raid": "raid-log", "jira-export": "jira-export", "analytics": "analytics",
}
DEFAULT_DOC_TYPE = "document"

SUPPORTED_EXTENSIONS = {".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv", ".docx": "docx"}
MAX_FILE_BYTES = 25 * 1024 * 1024
CSV_MAX_ROWS = 100_000
ENV_FILE = BASE_DIR / ".env"  # saved repo URL + PAT pairs (git-ignored)

# --- Sync (nightly check + Sync now) -------------------------------------
SYNC_DAILY_AT = os.environ.get("ASTRA_SYNC_DAILY_AT", "02:00")  # HH:MM in UTC
# Off: no nightly check, startup catch-up or startup index recovery (tests and maintenance only).
SYNC_SCHEDULER_ENABLED = os.environ.get("ASTRA_SYNC_SCHEDULER", "1") != "0"
SYNC_WORKERS = 1  # embedding is CPU-heavy; runs queue behind each other
SYNC_CATCHUP_HOURS = 24  # at startup, check repos not checked for this long (e.g. the server was down at night)
