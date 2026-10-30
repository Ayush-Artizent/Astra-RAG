import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from astra_rag.services.errors import AppError
from astra_rag.services.sources import git

HEADER = "Authorization: Basic c2VjcmV0LXRva2Vu"


class GitCloneTests(unittest.TestCase):
    def _run(self, branch=None):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("env")))
            return SimpleNamespace(stdout="abc123\n")

        with mock.patch.object(git.subprocess, "run", side_effect=fake_run):
            result = git.git_clone("https://h/x.git", Path("dest"), branch, HEADER)
        return result, calls

    def test_disables_symlinks_and_keeps_the_header_out_of_args(self):
        result, calls = self._run()
        cmd, env = calls[0]
        self.assertEqual(cmd[:4], ["git", "clone", "--depth", "1"])
        self.assertNotIn("--branch", cmd)
        self.assertNotIn("c2VjcmV0LXRva2Vu", " ".join(cmd))
        config = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                  for i in range(int(env["GIT_CONFIG_COUNT"]))}
        self.assertEqual(config["core.symlinks"], "false")
        self.assertEqual(config["http.extraheader"], HEADER)
        self.assertEqual((result.commit_sha, result.branch), ("abc123", "abc123"))

    def test_explicit_branch_is_cloned_alone(self):
        _, calls = self._run(branch="dev")
        cmd = calls[0][0]
        self.assertEqual(cmd[cmd.index("--branch") + 1], "dev")
        self.assertIn("--single-branch", cmd)

    def test_failures_become_safe_app_errors(self):
        cases = ((subprocess.TimeoutExpired("git", 1), 504),
                 (subprocess.CalledProcessError(128, "git", stderr=b"token=secret"), 502),
                 (FileNotFoundError(), 500))
        for exc, status in cases:
            with self.subTest(exc=type(exc).__name__), \
                    mock.patch.object(git.subprocess, "run", side_effect=exc):
                with self.assertRaises(AppError) as ctx:
                    git.git_clone("https://h/x.git", Path("dest"), None, HEADER)
                self.assertEqual(ctx.exception.status, status)
                self.assertNotIn("secret", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
