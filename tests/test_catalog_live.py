import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from astra_rag import create_app
from astra_rag.services.catalog import CatalogCache, build_catalog, service
from astra_rag.services.catalog.live import AdapterReader
from astra_rag.services.errors import AppError
from astra_rag.services.registry import repos, runs
from astra_rag.services.sources import PatCredential, adapter_for, parse_repo_url
from tests.helpers import use_temp_registry
from tests.sources.fake_http import FakeHttp
from tests.test_routes import SLUG, fake_adapter

FILES = {
    "policies.md": "## Data handling\nNo card numbers.\n",
    "nomenclature.md": "# Naming\nBRD-001\n",
    "golden.yaml": "rules:\n  - file: policies.md\n    section: Data handling\n    always: true\n",
    "templates/brd.md": "# BRD\n## Scope\n",
}


class FakeAdapter:
    """In-memory host: files by path, a blob sha per file, a movable branch head."""

    def __init__(self, files=None):
        self.files = dict(files or FILES)
        self.sha = "c1"
        self.calls = []
        self.fail = None

    def _check(self):
        if self.fail:
            raise self.fail

    def head_sha(self, branch):
        self._check()
        return self.sha

    def list_dir(self, path="", ref=None):
        self._check()
        self.calls.append(("list_dir", path, ref))
        prefix = f"{path}/" if path else ""
        names = {}
        for file, text in self.files.items():
            if not file.startswith(prefix):
                continue
            first, _, rest = file[len(prefix):].partition("/")
            if rest:
                names[first] = {"name": first, "type": "dir"}
            else:
                names[first] = {"name": first, "type": "file", "sha": f"blob-{len(text)}-{first}"}
        if not names and path:
            raise AppError("That path was not found in the repository.", 404)
        return list(names.values())

    def read_file(self, path, ref=None):
        self._check()
        self.calls.append(("read_file", path, ref))
        if path not in self.files:
            raise AppError("That path was not found in the repository.", 404)
        return self.files[path].encode()


class AdapterReaderTests(unittest.TestCase):
    def test_reads_are_pinned_to_the_commit_first_seen(self):
        adapter = FakeAdapter()
        reader = AdapterReader(adapter, "main")
        reader.list_dir("")
        adapter.sha = "c2"  # a push lands mid-build
        reader.read_file("policies.md")
        self.assertEqual(reader.head_sha(), "c1")
        self.assertEqual({ref for _, _, ref in adapter.calls}, {"c1"})

    def test_missing_file_and_folder_are_not_errors(self):
        reader = AdapterReader(FakeAdapter(), "main")
        self.assertIsNone(reader.read_file("nope.md"))
        self.assertEqual(reader.list_dir("nope"), [])

    def test_other_host_errors_still_raise(self):
        adapter = FakeAdapter()
        adapter.fail = AppError("The host rejected the token (401).", 401)
        with self.assertRaises(AppError):
            AdapterReader(adapter, "main").read_file("policies.md")

    def test_bytes_are_decoded_and_oversize_files_skipped(self):
        adapter = FakeAdapter({"a.md": "café"})
        self.assertEqual(AdapterReader(adapter, "main").read_file("a.md"), "café")
        with mock.patch("astra_rag.services.catalog.live.MAX_CATALOG_FILE_BYTES", 2):
            self.assertIsNone(AdapterReader(adapter, "main").read_file("a.md"))

    def test_catalog_builds_through_an_adapter(self):
        cat = build_catalog(AdapterReader(FakeAdapter(), "main"))
        self.assertEqual(cat.head_sha, "c1")
        self.assertEqual([r.selection for r in cat.rules if r.section.title == "Data handling"], ["always"])
        self.assertEqual([t.doc_type for t in cat.templates], ["BRD"])


class StaleCacheTests(unittest.TestCase):
    def test_unchanged_blobs_are_not_downloaded_again(self):
        adapter, cache = FakeAdapter(), CatalogCache()
        cache.get("k", AdapterReader(adapter, "main"))
        adapter.calls.clear()
        adapter.sha = "c2"
        cache.get("k", AdapterReader(adapter, "main"))
        self.assertEqual([c for c in adapter.calls if c[0] == "read_file"], [])

    def test_host_down_returns_the_last_catalog_marked_stale(self):
        adapter, cache = FakeAdapter(), CatalogCache()
        first = cache.get("k", AdapterReader(adapter, "main"))
        adapter.fail = AppError("Could not reach the host.", 502)
        stale = cache.get("k", AdapterReader(adapter, "main"))
        self.assertTrue(stale.stale)
        self.assertEqual(stale.head_sha, first.head_sha)
        adapter.fail = None
        self.assertFalse(cache.get("k", AdapterReader(adapter, "main")).stale)

    def test_host_down_with_nothing_cached_raises(self):
        adapter = FakeAdapter()
        adapter.fail = AppError("Could not reach the host.", 502)
        with self.assertRaises(AppError):
            CatalogCache().get("k", AdapterReader(adapter, "main"))


class HostEntryShapeTests(unittest.TestCase):
    def test_github_list_dir_carries_the_blob_sha_when_given(self):
        with FakeHttp() as http:
            http.add("/contents/", json.dumps([{"name": "policies.md", "type": "file", "sha": "abc"},
                                               {"name": "templates", "type": "dir"}]))
            adapter = adapter_for(parse_repo_url("https://github.com/acme/golden"), PatCredential("t"))
            self.assertEqual(adapter.list_dir(""), [{"name": "policies.md", "type": "file", "sha": "abc"},
                                                    {"name": "templates", "type": "dir"}])

    def test_azure_list_dir_carries_the_object_id(self):
        with FakeHttp() as http:
            http.add("/items", json.dumps({"value": [
                {"path": "/", "isFolder": True, "gitObjectType": "tree"},
                {"path": "/policies.md", "gitObjectType": "blob", "objectId": "obj1"}]}))
            adapter = adapter_for(parse_repo_url("https://dev.azure.com/org/proj/_git/golden"), PatCredential("t"))
            self.assertEqual(adapter.list_dir(""), [{"name": "policies.md", "type": "file", "sha": "obj1"}])


class CatalogRouteTests(unittest.TestCase):
    def setUp(self):
        use_temp_registry(self)
        service._cache = CatalogCache()
        self.client = TestClient(create_app())
        self.adapter = FakeAdapter()
        runs.register_and_queue(fake_adapter().ref, "https://github.com/acme/golden", "main", "ref")
        repos.bind_project("proj-1", SLUG)
        for target, new in (("adapter_for", mock.Mock(return_value=self.adapter)),
                            ("token_store.get_token", mock.Mock(return_value="tok"))):
            patcher = mock.patch(f"astra_rag.services.catalog.service.{target}", new)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_project_catalog(self):
        data = self.client.get("/api/projects/proj-1/catalog").json()
        self.assertTrue(data["ok"])
        self.assertEqual((data["repo"], data["branch"], data["head_sha"]), (SLUG, "main", "c1"))
        self.assertTrue(data["manifest_present"])
        self.assertFalse(data["stale"])
        self.assertEqual(data["templates"][0]["doc_type"], "BRD")
        self.assertNotIn("text", data["rules"][0])
        with_text = self.client.get("/api/projects/proj-1/catalog?include_text=true").json()
        self.assertIn("text", with_text["rules"][0])

    def test_repo_catalog_matches_project_catalog(self):
        by_repo = self.client.get(f"/api/repos/{SLUG}/catalog").json()
        self.assertEqual(by_repo["head_sha"], "c1")
        self.assertEqual(by_repo["warnings"], self.client.get("/api/projects/proj-1/catalog").json()["warnings"])

    def test_unbound_project_unknown_repo_and_bad_id(self):
        self.assertEqual(self.client.get("/api/projects/other/catalog").status_code, 404)
        self.assertEqual(self.client.get("/api/repos/github.com__x__y/catalog").status_code, 404)
        self.assertEqual(self.client.get("/api/projects/bad id!/catalog").status_code, 422)

    def test_missing_token_is_a_clear_error(self):
        with mock.patch("astra_rag.services.catalog.service.token_store.get_token", return_value=None):
            res = self.client.get("/api/projects/proj-1/catalog")
        self.assertEqual(res.status_code, 400)
        self.assertIn("token", res.json()["error"])

    def test_token_is_never_returned(self):
        self.assertNotIn('"tok"', json.dumps(self.client.get("/api/projects/proj-1/catalog").json()))


if __name__ == "__main__":
    unittest.main()
