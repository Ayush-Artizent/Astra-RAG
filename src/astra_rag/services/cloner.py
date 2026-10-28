"""Clones a repo into temp_storage/ without leaving the token on disk."""
import base64
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass

from ..config import GIT_TIMEOUT_SECONDS, TEMP_STORAGE_DIR
from .errors import AppError
from .github_client import RepoRef


@dataclass(frozen=True)
class CloneResult:
    path: str
    commit_sha: str
    branch: str


def clone_repo(repo: RepoRef, token: str) -> CloneResult:
    """Clone into temp_storage/<owner>__<name>, replacing any earlier clone."""
    TEMP_STORAGE_DIR.mkdir(exist_ok=True)
    target = TEMP_STORAGE_DIR / f"{repo.owner}__{repo.name}"
    if target.exists():
        shutil.rmtree(target, onexc=_make_writable)

    # The token goes in a one-off header: never in the URL or .git/config, and passed through
    # environment variables (not `-c` arguments) so it is not visible in the process list.
    # core.symlinks=false checks links out as plain files, so a repo cannot point outside the clone.
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    cmd = ["git", "clone", "--depth", "1", repo.clone_url, str(target)]
    env = {
        **os.environ, "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.extraheader", "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        "GIT_CONFIG_KEY_1": "core.symlinks", "GIT_CONFIG_VALUE_1": "false",
    }
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=GIT_TIMEOUT_SECONDS, env=env)
    except subprocess.TimeoutExpired:
        raise AppError("Cloning timed out.", 504) from None
    except subprocess.CalledProcessError:
        raise AppError("git clone failed. Check the token's repository permissions.", 502) from None
    except FileNotFoundError:
        raise AppError("git is not installed on the server.", 500) from None
    return CloneResult(str(target), _git_output(target, "rev-parse", "HEAD"),
                       _git_output(target, "rev-parse", "--abbrev-ref", "HEAD"))


def _git_output(repo_dir, *args: str) -> str:
    """Run a read-only git command in the clone; empty string if it fails."""
    try:
        out = subprocess.run(["git", "-C", str(repo_dir), *args], check=True, capture_output=True,
                             text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return ""
    return out.stdout.strip()


def _make_writable(func, path, _exc):
    """Windows marks .git objects read-only; clear that so rmtree can remove them."""
    os.chmod(path, stat.S_IWRITE)
    func(path)
