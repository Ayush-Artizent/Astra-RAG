import tempfile
import unittest
from pathlib import Path

from astra_rag.services import token_store
from astra_rag.services.repo_ref import parse_repo_url


class TokenStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.a = parse_repo_url("https://github.com/acme/golden")
        self.b = parse_repo_url("https://github.com/Manoj-B/other-repo")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_then_get_per_repo(self):
        token_store.save(self.a, "https://github.com/acme/golden", "tok-a", self.env)
        token_store.save(self.b, "https://github.com/Manoj-B/other-repo", "tok-b", self.env)
        self.assertEqual(token_store.get_token(self.a, self.env), "tok-a")
        self.assertEqual(token_store.get_token(self.b, self.env), "tok-b")
        text = self.env.read_text()
        self.assertIn("ASTRA_REPO_GITHUB_COM__ACME__GOLDEN_URL=https://github.com/acme/golden", text)
        self.assertIn("ASTRA_REPO_GITHUB_COM__ACME__GOLDEN_TOKEN=tok-a", text)

    def test_resave_replaces_instead_of_duplicating(self):
        token_store.save(self.a, "https://github.com/acme/golden", "old", self.env)
        token_store.save(self.a, "https://github.com/acme/golden", "new", self.env)
        self.assertEqual(token_store.get_token(self.a, self.env), "new")
        self.assertEqual(self.env.read_text().count("GOLDEN_TOKEN"), 1)

    def test_unknown_repo_and_missing_file_return_none(self):
        self.assertIsNone(token_store.get_token(self.a, self.env))
        token_store.save(self.b, "u", "t", self.env)
        self.assertIsNone(token_store.get_token(self.a, self.env))

    def test_unrelated_env_entries_are_preserved(self):
        self.env.write_text("OTHER_SETTING=keep-me\n", encoding="utf-8")
        token_store.save(self.a, "u", "t", self.env)
        self.assertIn("OTHER_SETTING=keep-me", self.env.read_text())

    def test_same_owner_and_name_on_another_host_has_its_own_token(self):
        enterprise = parse_repo_url("https://git.acme.com/acme/golden")
        token_store.save(self.a, "https://github.com/acme/golden", "public", self.env)
        token_store.save(enterprise, "https://git.acme.com/acme/golden", "private", self.env)
        self.assertEqual(token_store.get_token(self.a, self.env), "public")
        self.assertEqual(token_store.get_token(enterprise, self.env), "private")

    def test_legacy_key_is_migrated_once(self):
        self.env.write_text("ASTRA_REPO_ACME__GOLDEN_URL=https://github.com/acme/golden\n"
                            "ASTRA_REPO_ACME__GOLDEN_TOKEN=old-tok\nOTHER=keep\n", encoding="utf-8")
        self.assertEqual(token_store.get_token(self.a, self.env), "old-tok")
        text = self.env.read_text()
        self.assertNotIn("ASTRA_REPO_ACME__GOLDEN_", text)
        self.assertIn("ASTRA_REPO_GITHUB_COM__ACME__GOLDEN_TOKEN=old-tok", text)
        self.assertIn("OTHER=keep", text)
        self.assertEqual(token_store.get_token(self.a, self.env), "old-tok")

    def test_legacy_key_of_another_host_is_left_alone(self):
        self.env.write_text("ASTRA_REPO_ACME__GOLDEN_URL=https://git.acme.com/acme/golden\n"
                            "ASTRA_REPO_ACME__GOLDEN_TOKEN=ghe-tok\n", encoding="utf-8")
        self.assertIsNone(token_store.get_token(self.a, self.env))
        self.assertIn("ASTRA_REPO_ACME__GOLDEN_TOKEN=ghe-tok", self.env.read_text())
        enterprise = parse_repo_url("https://git.acme.com/acme/golden")
        self.assertEqual(token_store.get_token(enterprise, self.env), "ghe-tok")

    def test_save_drops_the_legacy_entry(self):
        self.env.write_text("ASTRA_REPO_ACME__GOLDEN_URL=https://github.com/acme/golden\n"
                            "ASTRA_REPO_ACME__GOLDEN_TOKEN=old-tok\n", encoding="utf-8")
        token_store.save(self.a, "https://github.com/acme/golden", "new-tok", self.env)
        text = self.env.read_text()
        self.assertNotIn("old-tok", text)
        self.assertEqual(token_store.get_token(self.a, self.env), "new-tok")

    def test_forget_removes_only_that_repo(self):
        token_store.save(self.a, "u", "ta", self.env)
        token_store.save(self.b, "u", "tb", self.env)
        self.assertTrue(token_store.forget(self.a, self.env))
        self.assertIsNone(token_store.get_token(self.a, self.env))
        self.assertEqual(token_store.get_token(self.b, self.env), "tb")
        self.assertFalse(token_store.forget(self.a, self.env))


if __name__ == "__main__":
    unittest.main()
