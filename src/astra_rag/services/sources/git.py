"""Host-neutral `git clone`: an adapter supplies only its auth header and clone URL."""
import os
import subprocess
from pathlib import Path

from ...config import GIT_TIMEOUT_SECONDS
from ..errors import AppError
from .base import CloneResult


def git_clone(clone_url: str, dest: Path, branch: str | None, auth_header: str) -> CloneResult:
    # The header goes in a one-off env-var config: never in the URL or .git/config, and not in
    # argv (`-c`), so it is not visible in the process list.
    # core.symlinks=false checks links out as plain files, so a repo cannot point outside the clone.
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch, "--single-branch"]
    cmd += [clone_url, str(dest)]
    env = {
        **os.environ, "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.extraheader", "GIT_CONFIG_VALUE_0": auth_header,
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
    return CloneResult(str(dest), git_output(dest, "rev-parse", "HEAD"),
                       git_output(dest, "rev-parse", "--abbrev-ref", "HEAD"))


def git_output(repo_dir, *args: str) -> str:
    """Run a read-only git command in the clone; empty string if it fails."""
    try:
        out = subprocess.run(["git", "-C", str(repo_dir), *args], check=True, capture_output=True,
                             text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return ""
    return out.stdout.strip()
