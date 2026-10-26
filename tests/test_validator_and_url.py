import unittest

from app.services.errors import AppError
from app.services.github_client import parse_repo_url
from app.services.validator import find_missing

FULL = [
    {"name": "policies.md", "type": "file"},
    {"name": "nomenclature.md", "type": "file"},
    {"name": "project-data", "type": "dir"},
    {"name": "templates", "type": "dir"},
]


class ValidatorTests(unittest.TestCase):
    def test_all_present(self):
        self.assertEqual(find_missing(FULL), [])

    def test_reports_each_missing_item(self):
        self.assertEqual(find_missing(FULL[1:3]), ["policies.md", "templates/"])

    def test_wrong_type_counts_as_missing(self):
        entries = [{"name": "templates", "type": "file"}] + FULL[:3]
        self.assertEqual(find_missing(entries), ["templates/"])


class UrlTests(unittest.TestCase):
    def test_parses_with_git_suffix(self):
        r = parse_repo_url("https://github.com/acme/repo.git")
        self.assertEqual((r.owner, r.name), ("acme", "repo"))
        self.assertEqual(r.api_base, "https://api.github.com")

    def test_rejects_bad_urls(self):
        for bad in ("", "http://github.com/a/b", "https://github.com/a"):
            with self.assertRaises(AppError):
                parse_repo_url(bad)


if __name__ == "__main__":
    unittest.main()
