import unittest

from astra_rag.services.errors import AppError
from astra_rag.services.ingestion.store import collection_name
from astra_rag.services.sources.registry import parse_repo_url
from astra_rag.services.validator import find_missing

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

    def test_github_ref_is_host_aware(self):
        r = parse_repo_url("https://github.com/Acme/Golden/tree/main")
        self.assertEqual((r.host_kind, r.host, r.path_parts, r.name), ("github", "github.com", ("Acme",), "Golden"))
        self.assertEqual(r.slug, "github.com__acme__golden")

    def test_same_owner_and_name_on_two_hosts_do_not_collide(self):
        public = parse_repo_url("https://github.com/acme/golden")
        enterprise = parse_repo_url("https://git.acme.com/acme/golden")
        self.assertEqual(enterprise.host_kind, "ghe")
        self.assertNotEqual(public.slug, enterprise.slug)
        self.assertNotEqual(collection_name(public.slug), collection_name(enterprise.slug))

    def test_other_hosts_are_not_supported_yet(self):
        for url, label in (("https://dev.azure.com/org/proj/_git/repo", "Azure DevOps"),
                           ("https://org.visualstudio.com/proj/_git/repo", "Azure DevOps"),
                           ("https://gitlab.com/group/sub/repo", "GitLab"),
                           ("https://bitbucket.org/team/repo", "Bitbucket")):
            with self.assertRaises(AppError) as ctx:
                parse_repo_url(url)
            self.assertIn(f"{label} repositories are not supported yet", ctx.exception.message)

    def test_rejects_bad_urls(self):
        for bad in ("", "http://github.com/a/b", "https://github.com/a"):
            with self.assertRaises(AppError):
                parse_repo_url(bad)


if __name__ == "__main__":
    unittest.main()
