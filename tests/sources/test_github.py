import base64
import json
import unittest
from urllib.parse import urlparse

from astra_rag.services.errors import AppError
from astra_rag.services.sources import PatCredential, adapter_for, parse_repo_url
from astra_rag.services.sources.github import GitHubAdapter

from .contract import TOKEN, AdapterContract
from .fake_http import FakeHttp

API = "https://api.github.com/repos/acme/golden"


class GitHubContractTests(AdapterContract, unittest.TestCase):
    def make_adapter(self, token=TOKEN):
        return adapter_for(parse_repo_url("https://github.com/acme/golden"),
                           PatCredential(token) if token else None)

    def stub_list_dir(self, http, path, entries):
        url = f"{API}/contents/{path}" + ("" if path else "")
        http.add(url if path else f"{API}/contents/", json.dumps([{"name": n, "type": t} for n, t in entries]))

    def stub_file(self, http, path, body):
        http.add(f"{API}/contents/{path}", body)

    def stub_head(self, http, branch, sha):
        http.add(f"{API}/git/ref/heads/{branch}", json.dumps({"object": {"sha": sha}}))

    def stub_default_branch(self, http, name):
        http.add(API, json.dumps({"default_branch": name}))

    def stub_ancestry(self, http, base, head, is_ancestor):
        http.add(f"/compare/{base}...{head}", json.dumps({"status": "ahead" if is_ancestor else "behind"}))


class GitHubSpecificTests(unittest.TestCase):
    def setUp(self):
        self.adapter = adapter_for(parse_repo_url("https://github.com/Acme/Golden"), PatCredential("tok"))
        self.http = FakeHttp()
        self.http.__enter__()
        self.addCleanup(self.http.__exit__)

    def test_urls_for_github_and_enterprise(self):
        self.assertEqual(self.adapter.clone_url, "https://github.com/Acme/Golden.git")
        self.assertEqual(self.adapter.api_base, "https://api.github.com")
        enterprise = adapter_for(parse_repo_url("https://git.acme.com/acme/golden"))
        self.assertEqual(enterprise.api_base, "https://git.acme.com/api/v3")
        self.assertEqual(enterprise.clone_url, "https://git.acme.com/acme/golden.git")

    def test_root_listing_matches_the_original_request(self):
        self.http.add("/contents/", "[]")
        self.adapter.list_dir("")
        request = self.http.requests[-1]
        self.assertEqual(request.full_url, "https://api.github.com/repos/Acme/Golden/contents/")
        headers = self.http.last_headers()
        self.assertEqual(headers["authorization"], "Bearer tok")
        self.assertEqual(headers["accept"], "application/vnd.github+json")
        self.assertEqual(headers["user-agent"], "astra-rag")

    def test_ref_is_sent_as_a_query_parameter(self):
        self.http.add("/contents/templates", "[]")
        self.adapter.list_dir("templates", ref="dev")
        self.assertEqual(urlparse(self.http.requests[-1].full_url).query, "ref=dev")

    def test_read_file_asks_for_the_raw_body(self):
        self.http.add("/contents/a.md", b"x")
        self.adapter.read_file("a.md", ref="abc")
        self.assertEqual(self.http.last_headers()["accept"], "application/vnd.github.raw+json")

    def test_clone_uses_the_x_access_token_basic_header(self):
        from unittest import mock
        from astra_rag.services.sources import github
        with mock.patch.object(github, "git_clone") as clone:
            self.adapter.clone("dest", "dev")
        url, dest, branch, header = clone.call_args.args
        self.assertEqual((url, dest, branch), ("https://github.com/Acme/Golden.git", "dest", "dev"))
        self.assertEqual(header, "Authorization: Basic " + base64.b64encode(b"x-access-token:tok").decode())

    def test_citation_url_is_the_blob_link_pinned_to_the_ref(self):
        self.assertEqual(self.adapter.citation_url("project-data/a b.md", "abc", (3, 7)),
                         "https://github.com/Acme/Golden/blob/abc/project-data/a%20b.md#L3-L7")
        self.assertEqual(self.adapter.citation_url("x.md", "main"), "https://github.com/Acme/Golden/blob/main/x.md")

    def test_original_error_messages_are_kept(self):
        self.http.fail_with_status(401)
        with self.assertRaises(AppError) as ctx:
            self.adapter.list_dir("")
        self.assertEqual(ctx.exception.message,
                         "GitHub rejected the token (401). Check that the PAT is valid and not expired.")

    def test_unexpected_reply_shapes_are_a_502(self):
        self.http.add("/contents/", '{"not": "a list"}')
        self.http.add("/git/ref/heads/main", "{}")
        for call in (lambda: self.adapter.list_dir(""), lambda: self.adapter.head_sha("main")):
            with self.assertRaises(AppError) as ctx:
                call()
            self.assertEqual(ctx.exception.status, 502)


if __name__ == "__main__":
    unittest.main()
