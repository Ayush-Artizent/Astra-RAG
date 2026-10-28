import unittest
from types import SimpleNamespace
from unittest import mock

from astra_rag.services import cloner
from astra_rag.services.github_client import RepoRef


class ClonerTests(unittest.TestCase):
    def test_clone_disables_symlinks_and_keeps_token_out_of_args(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("env")))
            return SimpleNamespace(stdout="abc123\n")

        with mock.patch.object(cloner.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(cloner.shutil, "rmtree"), \
                mock.patch.object(cloner, "TEMP_STORAGE_DIR") as storage:
            storage.__truediv__.return_value.exists.return_value = False
            cloner.clone_repo(RepoRef("github.com", "acme", "golden"), "secret-token")

        cmd, env = calls[0]
        self.assertEqual(cmd[:2], ["git", "clone"])
        self.assertNotIn("secret-token", " ".join(cmd))
        config = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                  for i in range(int(env["GIT_CONFIG_COUNT"]))}
        self.assertEqual(config["core.symlinks"], "false")
        self.assertTrue(config["http.extraheader"].startswith("Authorization: Basic "))


if __name__ == "__main__":
    unittest.main()
