import unittest
from pathlib import Path
from unittest import mock

from astra_rag.services import cloner
from astra_rag.services.sources import CloneResult, adapter_for, parse_repo_url


class ClonerTests(unittest.TestCase):
    def setUp(self):
        self.adapter = adapter_for(parse_repo_url("https://github.com/acme/golden"))

    def _clone(self, exists: bool, branch=None):
        result = CloneResult("x", "abc123", "main")
        with mock.patch.object(cloner, "TEMP_STORAGE_DIR") as storage, \
                mock.patch.object(cloner.shutil, "rmtree") as rmtree, \
                mock.patch.object(type(self.adapter), "clone", return_value=result) as clone:
            target = storage.__truediv__.return_value
            target.exists.return_value = exists
            out = cloner.clone_repo(self.adapter, branch)
        return out, storage, target, rmtree, clone

    def test_clones_into_a_folder_named_after_the_host_aware_slug(self):
        out, storage, target, rmtree, clone = self._clone(exists=False)
        storage.__truediv__.assert_called_with("github.com__acme__golden")
        clone.assert_called_once_with(target, None)
        rmtree.assert_not_called()
        self.assertEqual(out.commit_sha, "abc123")

    def test_an_earlier_clone_is_replaced(self):
        _, _, target, rmtree, _ = self._clone(exists=True, branch="dev")
        rmtree.assert_called_once()
        self.assertIs(rmtree.call_args.args[0], target)

    def test_branch_is_passed_to_the_adapter(self):
        _, _, target, _, clone = self._clone(exists=False, branch="dev")
        clone.assert_called_once_with(target, "dev")


if __name__ == "__main__":
    unittest.main()
