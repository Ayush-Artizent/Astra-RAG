"""Central settings: what a repo must contain, where clones go, and env-driven config."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
BASE_DIR = PACKAGE_DIR.parent.parent  # repo root
TEMP_STORAGE_DIR = BASE_DIR / "temp_storage"
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# Names must match exactly (case-sensitive) at the repository root.
REQUIRED_FILES = ("policies.md", "nomenclature.md")
TEMPLATES_FOLDER = "templates"
REQUIRED_FOLDERS = ("project-data", TEMPLATES_FOLDER)

GIT_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 20

# --- RAG ingestion -------------------------------------------------------
PROJECT_DATA_DIR_NAME = "project-data"
CACHE_DIR = BASE_DIR / ".cache"
ENV_FILE = BASE_DIR / ".env"  # env-driven settings + saved repo URL/PAT pairs (git-ignored)


class Settings(BaseSettings):
    """Env-driven settings, read from the environment and `.env` (env wins).

    The repo URL and PAT are not here: they come from the connect flow (`services/token_store.py`).
    """
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    fastembed_cache_dir: Path = CACHE_DIR / "fastembed"


def get_settings() -> Settings:
    """Build settings fresh each call so edits to `.env` apply without a restart."""
    return Settings()


_startup = get_settings()
FASTEMBED_CACHE_DIR = _startup.fastembed_cache_dir
QDRANT_URL = _startup.qdrant_url
QDRANT_API_KEY = _startup.qdrant_api_key or None
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
CSV_SUMMARY_SAMPLE_ROWS = 3

SUPPORTED_EXTENSIONS = {".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv", ".docx": "docx"}
MAX_FILE_BYTES = 25 * 1024 * 1024
CSV_MAX_ROWS = 100_000

# --- W2 document-context tool --------------------------------------------
# A template is a file directly in `templates/` with one of these extensions;
# its request type is the filename stem uppercased (brd.md -> BRD).
TEMPLATE_EXTENSIONS = (".md",)
TEMPLATE_ALIASES: dict[str, str] = {}  # e.g. {"REQUIREMENTS": "BRD"} (uppercase -> uppercase)
TOOL_MAX_FILE_BYTES = 256 * 1024
