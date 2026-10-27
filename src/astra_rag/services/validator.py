"""Checks a repo-root listing against the required structure."""
from ..config import REQUIRED_FILES, REQUIRED_FOLDERS


def find_missing(entries: list[dict]) -> list[str]:
    """Return human-readable names of required items that are absent."""
    files = {e["name"] for e in entries if e["type"] == "file"}
    dirs = {e["name"] for e in entries if e["type"] == "dir"}
    missing = [f for f in REQUIRED_FILES if f not in files]
    missing += [f"{d}/" for d in REQUIRED_FOLDERS if d not in dirs]
    return missing
