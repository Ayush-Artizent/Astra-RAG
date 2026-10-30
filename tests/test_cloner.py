import os
import stat
import tempfile
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


class RemoveCloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(cloner, "TEMP_STORAGE_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_clone(self, name):
        objects = self.root / name / ".git" / "objects"
        objects.mkdir(parents=True)
        pack = objects / "pack"
        pack.write_text("x")
        os.chmod(pack, stat.S_IREAD)  # git marks objects read-only; Windows refuses to delete them otherwise
        return self.root / name

    def test_remove_clone_deletes_the_folder_including_read_only_files(self):
        clone = self.make_clone("github.com__acme__golden")
        cloner.remove_clone("github.com__acme__golden")
        self.assertFalse(clone.exists())

    def test_remove_clone_of_nothing_is_fine(self):
        cloner.remove_clone("github.com__acme__nope")

    def test_remove_clone_never_raises(self):
        self.make_clone("github.com__acme__golden")
        with mock.patch.object(cloner.shutil, "rmtree", side_effect=PermissionError("locked")):
            cloner.remove_clone("github.com__acme__golden")

    def test_sweep_removes_every_clone_but_keeps_the_gitkeep(self):
        (self.root / ".gitkeep").write_text("")
        first, second = self.make_clone("a"), self.make_clone("b")
        cloner.sweep()
        self.assertFalse(first.exists() or second.exists())
        self.assertTrue((self.root / ".gitkeep").exists())

    def test_sweep_without_a_storage_folder_is_fine(self):
        with mock.patch.object(cloner, "TEMP_STORAGE_DIR", self.root / "missing"):
            cloner.sweep()


if __name__ == "__main__":
    unittest.main()
