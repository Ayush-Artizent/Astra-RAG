"""Clones a repo into temp_storage/ without leaving the token on disk."""
import base64
import os
import shutil
import stat
import subprocess

from ..config import GIT_TIMEOUT_SECONDS, TEMP_STORAGE_DIR
from .errors import AppError
from .github_client import RepoRef


def clone_repo(repo: RepoRef, token: str) -> str:
    """Clone into temp_storage/<owner>__<name>, replacing any earlier clone. Returns the path."""
    TEMP_STORAGE_DIR.mkdir(exist_ok=True)
    target = TEMP_STORAGE_DIR / f"{repo.owner}__{repo.name}"
    if target.exists():
        shutil.rmtree(target, onexc=_make_writable)

    # Pass the token as a one-off header so it is never written to .git/config.
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    cmd = [
        "git", "-c", f"http.extraheader=Authorization: Basic {basic}",
        "clone", "--depth", "1", repo.clone_url, str(target),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=GIT_TIMEOUT_SECONDS,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise AppError("Cloning timed out.", 504) from None
    except subprocess.CalledProcessError:
        raise AppError("git clone failed. Check the token's repository permissions.", 502) from None
    except FileNotFoundError:
        raise AppError("git is not installed on the server.", 500) from None
    return str(target)


def _make_writable(func, path, _exc):
    """Windows marks .git objects read-only; clear that so rmtree can remove them."""
    os.chmod(path, stat.S_IWRITE)
    func(path)
