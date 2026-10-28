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

# Host kinds a repo URL may point at today (see services/repo_ref.host_kind).
SUPPORTED_HOST_KINDS = ("github", "ghe")

GIT_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 20

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
CSV_SUMMARY_SAMPLE_ROWS = 3

SUPPORTED_EXTENSIONS = {".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv", ".docx": "docx"}
MAX_FILE_BYTES = 25 * 1024 * 1024
CSV_MAX_ROWS = 100_000
ENV_FILE = BASE_DIR / ".env"  # saved repo URL + PAT pairs (git-ignored)
