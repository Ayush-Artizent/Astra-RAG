import base64
import json
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from astra_rag.services.errors import AppError
from astra_rag.services.sources import PatCredential, adapter_for, azure_devops, parse_repo_url

from .contract import TOKEN, AdapterContract
from .fake_http import FakeHttp

URL = "https://dev.azure.com/acme/proj/_git/golden"
API = "https://dev.azure.com/acme/proj/_apis/git/repositories/golden"
SHA = "a" * 40


class AzureDevOpsContractTests(AdapterContract, unittest.TestCase):
    def make_adapter(self, token=TOKEN):
        return adapter_for(parse_repo_url(URL), PatCredential(token) if token else None)

    def stub_list_dir(self, http, path, entries):
        items = [{"path": "/" + path, "isFolder": True, "gitObjectType": "tree"}]  # the folder itself comes first
        items += [{"path": f"/{path}/{n}".replace("//", "/"), "isFolder": t == "dir",
                   "gitObjectType": "tree" if t == "dir" else "blob"} for n, t in entries]
        http.add(f"{API}/items?scopePath=/{path}&recursionLevel=OneLevel", json.dumps({"value": items}))

    def stub_file(self, http, path, body):
        http.add(f"{API}/items?path=/{path}", body)

    def stub_head(self, http, branch, sha):
        http.add(f"{API}/refs?filter=heads/{branch}",
                 json.dumps({"value": [{"name": f"refs/heads/{branch}-old", "objectId": "0" * 40},
                                       {"name": f"refs/heads/{branch}", "objectId": sha}]}))

    def stub_default_branch(self, http, name):
        http.add(API, json.dumps({"defaultBranch": f"refs/heads/{name}"}))

    def stub_ancestry(self, http, base, head, is_ancestor):
        http.add(f"baseVersion={base}&baseVersionType=commit&targetVersion={head}",
                 json.dumps({"aheadCount": 1, "behindCount": 0 if is_ancestor else 2}))


class UrlParsingTests(unittest.TestCase):
    def test_all_accepted_forms_give_the_same_repo(self):
        for url in (URL,
                    "https://acme@dev.azure.com/acme/proj/_git/golden",
                    "https://dev.azure.com/acme/proj/_git/golden/?path=/x",
                    "https://acme.visualstudio.com/proj/_git/golden",
                    "https://acme.visualstudio.com/DefaultCollection/proj/_git/golden"):
            with self.subTest(url=url):
                ref = parse_repo_url(url)
                self.assertEqual((ref.host_kind, ref.host, ref.path_parts, ref.name),
                                 ("azure_devops", "dev.azure.com", ("acme", "proj"), "golden"))
                self.assertEqual(ref.slug, "dev.azure.com__acme__proj__golden")

    def test_web_url_drops_credentials_query_and_fragment(self):
        for typed in ("https://org@dev.azure.com/org/proj/_git/golden?path=/policies.md&version=GBmain#x",
                      "https://user:hunter2@org.visualstudio.com/DefaultCollection/proj/_git/golden?a=b"):
            with self.subTest(url=typed):
                self.assertEqual(adapter_for(parse_repo_url(typed)).web_url,
                                 "https://dev.azure.com/org/proj/_git/golden")

    def test_shorthand_uses_the_repo_name_as_the_project(self):
        for url in ("https://dev.azure.com/acme/_git/golden", "https://acme.visualstudio.com/_git/golden"):
            ref = parse_repo_url(url)
            self.assertEqual(ref.path_parts, ("acme", "golden"))

    def test_encoded_names_are_decoded_and_re_encoded(self):
        ref = parse_repo_url("https://dev.azure.com/acme/My%20Project/_git/golden%20repo")
        self.assertEqual((ref.path_parts, ref.name), (("acme", "My Project"), "golden repo"))
        adapter = adapter_for(ref)
        self.assertEqual(adapter.clone_url, "https://dev.azure.com/acme/My%20Project/_git/golden%20repo")

    def test_bad_shapes_are_rejected(self):
        for bad in ("https://dev.azure.com/acme/proj/golden", "https://dev.azure.com/acme/proj/_git",
                    "https://dev.azure.com/_git/golden", "https://dev.azure.com/a/b/c/_git/golden",
                    "https://dev.azure.com/acme/../_git/golden", "https://dev.azure.com/acme/p%3Aq/_git/golden"):
            with self.subTest(url=bad), self.assertRaises(AppError):
                parse_repo_url(bad)


class AzureDevOpsSpecificTests(unittest.TestCase):
    def setUp(self):
        self.adapter = adapter_for(parse_repo_url(URL), PatCredential("tok"))
        self.http = FakeHttp()
        self.http.__enter__()
        self.addCleanup(self.http.__exit__)

    def test_requests_use_basic_auth_with_an_empty_user(self):
        self.http.add("/items", json.dumps({"value": []}))
        self.adapter.list_dir("")
        headers = self.http.last_headers()
        self.assertEqual(headers["authorization"], "Basic " + base64.b64encode(b":tok").decode())
        self.assertEqual(headers["accept"], "application/json")

    def test_query_parameters(self):
        self.http.add("/items", json.dumps({"value": []}))
        self.adapter.list_dir("templates", ref=SHA)
        query = parse_qs(urlparse(self.http.requests[-1].full_url).query)
        self.assertEqual(query["scopePath"], ["/templates"])
        self.assertEqual(query["recursionLevel"], ["OneLevel"])
        self.assertEqual(query["versionDescriptor.version"], [SHA])
        self.assertEqual(query["versionDescriptor.versionType"], ["commit"])
        self.assertEqual(query["api-version"], ["7.1"])
        self.adapter.list_dir("templates", ref="dev")
        self.assertEqual(parse_qs(urlparse(self.http.requests[-1].full_url).query)["versionDescriptor.versionType"],
                         ["branch"])

    def test_list_dir_drops_the_folder_itself_and_reports_object_types(self):
        self.http.add("/items", json.dumps({"value": [
            {"path": "/", "isFolder": True},
            {"path": "/policies.md", "gitObjectType": "blob"},
            {"path": "/templates", "gitObjectType": "tree", "isFolder": True},
            {"path": "/vendor", "gitObjectType": "commit"},
        ]}))
        self.assertEqual(self.adapter.list_dir(""), [{"name": "policies.md", "type": "file"},
                                                     {"name": "templates", "type": "dir"},
                                                     {"name": "vendor", "type": "submodule"}])

    def test_read_file_asks_for_the_raw_body_and_encodes_spaces(self):
        self.http.add("/items", b"x")
        self.adapter.read_file("project-data/a b.md", ref="main")
        request = self.http.requests[-1]
        self.assertEqual(self.http.last_headers()["accept"], "application/octet-stream")
        self.assertIn("path=/project-data/a%20b.md", request.full_url)
        self.assertIn("%24format=octetStream", request.full_url)

    def test_head_sha_needs_an_exact_branch_match(self):
        self.http.add("/refs", json.dumps({"value": [{"name": "refs/heads/main-old", "objectId": SHA}]}))
        with self.assertRaises(AppError) as ctx:
            self.adapter.head_sha("main")
        self.assertEqual(ctx.exception.status, 404)

    def test_empty_repo_has_no_default_branch(self):
        self.http.add(API, "{}")
        with self.assertRaises(AppError) as ctx:
            self.adapter.default_branch()
        self.assertEqual(ctx.exception.status, 409)

    def test_a_sign_in_page_means_the_token_was_rejected(self):
        # ADO answers a bad PAT with 203 and an HTML page rather than a 401.
        self.http.add("/items", "<!DOCTYPE html><html>Sign In</html>", status=203)
        with self.assertRaises(AppError) as ctx:
            self.adapter.list_dir("")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("rejected the token", ctx.exception.message)

    def test_unexpected_reply_shapes_are_a_502(self):
        self.http.add("/items", '{"not": "a list"}')
        self.http.add("/refs", "{}")
        for call in (lambda: self.adapter.list_dir(""), lambda: self.adapter.head_sha("main")):
            with self.assertRaises(AppError) as ctx:
                call()
            self.assertEqual(ctx.exception.status, 502)

    def test_clone_uses_the_basic_header_and_the_repo_url(self):
        with mock.patch.object(azure_devops, "git_clone") as clone:
            self.adapter.clone("dest", "dev")
        url, dest, branch, header = clone.call_args.args
        self.assertEqual((url, dest, branch), (URL, "dest", "dev"))
        self.assertEqual(header, "Authorization: Basic " + base64.b64encode(b":tok").decode())

    def test_citation_url_pins_a_commit_or_a_branch(self):
        self.assertEqual(self.adapter.citation_url("project-data/a b.md", SHA, (3, 7)),
                         f"{URL}?path=/project-data/a%20b.md&version=GC{SHA}"
                         "&line=3&lineEnd=8&lineStartColumn=1&lineEndColumn=1")
        self.assertEqual(self.adapter.citation_url("x.md", "main"), f"{URL}?path=/x.md&version=GBmain")

    def test_required_root_names_stay_case_sensitive(self):
        # ADO looks paths up case-insensitively, but the validator compares the names it lists.
        from astra_rag.services.validator import find_missing
        self.http.add("/items", json.dumps({"value": [{"path": "/Policies.md", "gitObjectType": "blob"}]}))
        self.assertIn("policies.md", find_missing(self.adapter.list_dir("")))


if __name__ == "__main__":
    unittest.main()
