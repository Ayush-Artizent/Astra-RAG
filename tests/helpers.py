import tempfile
import unittest
from pathlib import Path

from astra_rag.services.registry import db


def use_temp_registry(test: unittest.TestCase) -> Path:
    """Point the registry at a fresh SQLite file for this test; restored afterwards."""
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    path = Path(tmp.name) / "astra.db"
    db.use_db(path)
    test.addCleanup(tmp.cleanup)
    test.addCleanup(db.use_db, None)
    return path
