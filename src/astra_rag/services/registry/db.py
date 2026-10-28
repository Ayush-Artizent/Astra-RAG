"""SQLite connection, transactions and schema migrations. All registry SQL lives in this package."""
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ...config import DB_BUSY_TIMEOUT_SECONDS, DB_PATH
from ..errors import AppError

# Entry i upgrades the schema from version i to i + 1. Never edit a shipped entry; append a new one.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """CREATE TABLE repos (
            slug TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            host_kind TEXT NOT NULL,
            host TEXT NOT NULL,
            tracked_branch TEXT NOT NULL,
            config_version INTEGER NOT NULL DEFAULT 1,
            credential_ref TEXT NOT NULL,
            indexed_run_id INTEGER REFERENCES ingestion_runs(id),
            indexed_branch TEXT,
            indexed_commit_sha TEXT,
            indexed_collection TEXT,
            indexed_config_version INTEGER,
            indexed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE project_bindings (
            project_id TEXT PRIMARY KEY,
            repo_slug TEXT NOT NULL REFERENCES repos(slug),
            bound_at TEXT NOT NULL
        )""",
        "CREATE INDEX project_bindings_repo ON project_bindings(repo_slug)",
        """CREATE TABLE ingestion_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_slug TEXT NOT NULL REFERENCES repos(slug),
            state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed')),
            branch TEXT NOT NULL,
            config_version INTEGER NOT NULL,
            commit_sha TEXT NOT NULL DEFAULT '',
            collection TEXT NOT NULL DEFAULT '',
            index_replaced INTEGER NOT NULL DEFAULT 0,
            files_loaded INTEGER NOT NULL DEFAULT 0,
            files_skipped TEXT NOT NULL DEFAULT '[]',
            chunks_total INTEGER NOT NULL DEFAULT 0,
            chunks_stored INTEGER NOT NULL DEFAULT 0,
            warnings TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT '',
            queued_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT ''
        )""",
        "CREATE INDEX ingestion_runs_repo ON ingestion_runs(repo_slug, id)",
    ),
)

_path = DB_PATH
_ready: set[Path] = set()
_init_lock = threading.Lock()


def use_db(path: Path | None) -> None:
    """Point the registry at another file (tests); None restores the configured path."""
    global _path
    _path = Path(path) if path else DB_PATH


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def schema_version() -> int:
    return len(MIGRATIONS)


def _open() -> sqlite3.Connection:
    _path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: no implicit transactions, every one is started explicitly below.
    db = sqlite3.connect(_path, timeout=DB_BUSY_TIMEOUT_SECONDS, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_SECONDS * 1000}")
    return db


def migrate() -> None:
    """Bring the schema up to date in one transaction. A newer schema than this code knows is refused."""
    with closing(_open()) as db:
        db.execute("PRAGMA journal_mode = WAL")  # readers don't block the ingestion writer
        db.execute("BEGIN IMMEDIATE")
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > schema_version():
                raise AppError(f"The registry database has schema version {version}, newer than this app "
                               f"supports ({schema_version()}). Refusing to use it.", 500)
            for number in range(version, schema_version()):
                for statement in MIGRATIONS[number]:
                    db.execute(statement)
                db.execute(f"PRAGMA user_version = {number + 1}")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    _ready.add(_path)


def _ensure_ready() -> None:
    if _path not in _ready:
        with _init_lock:
            if _path not in _ready:
                migrate()


@contextmanager
def transaction(write: bool = True):
    """One connection, one transaction: commit on success, roll back on any error.

    Writes take the database write lock up front (BEGIN IMMEDIATE), so a check-then-insert inside one
    write transaction cannot interleave with another request's.
    """
    _ensure_ready()
    with closing(_open()) as db:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield db
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
