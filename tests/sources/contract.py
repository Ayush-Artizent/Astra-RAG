"""Behaviour every SourceAdapter must have. Not collected by itself: mix it into a TestCase.

A host's test class supplies `make_adapter` and the `stub_*` hooks that script that host's REST
replies; the tests below then check the same observable behaviour for every host.
"""
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from astra_rag.services.errors import AppError
from astra_rag.services.sources import git
from astra_rag.services.sources.credentials import PatCredential

from .fake_http import FakeHttp

TOKEN = "tok-SECRET-123"
HTTP_ERRORS = {401: 401, 403: 403, 429: 403, 404: 404, 409: 409, 500: 502}


def _git(cwd, *args):
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args]
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class AdapterContract:
    # --- hooks a host's test class must provide -------------------------------------------
    def make_adapter(self, token: str | None = TOKEN):
        raise NotImplementedError

    def stub_list_dir(self, http: FakeHttp, path: str, entries: list[tuple[str, str]]): ...
    def stub_file(self, http: FakeHttp, path: str, body: bytes): ...
    def stub_head(self, http: FakeHttp, branch: str, sha: str): ...
    def stub_default_branch(self, http: FakeHttp, name: str): ...
    def stub_ancestry(self, http: FakeHttp, base: str, head: str, is_ancestor: bool): ...

    # --- shared tests ---------------------------------------------------------------------
    def setUp(self):
        self.http = FakeHttp()
        self.http.__enter__()
        self.addCleanup(self.http.__exit__)

    def test_list_dir_root_and_subfolder(self):
        self.stub_list_dir(self.http, "", [("policies.md", "file"), ("templates", "dir")])
        self.stub_list_dir(self.http, "templates", [("brd.md", "file")])
        adapter = self.make_adapter()
        self.assertEqual(adapter.list_dir(""), [{"name": "policies.md", "type": "file"},
                                                {"name": "templates", "type": "dir"}])
        self.assertEqual(adapter.list_dir("templates"), [{"name": "brd.md", "type": "file"}])

    def test_read_file_returns_bytes(self):
        self.stub_file(self.http, "policies.md", b"# Policies\n")
        self.assertEqual(self.make_adapter().read_file("policies.md"), b"# Policies\n")

    def test_head_sha_and_default_branch(self):
        self.stub_head(self.http, "main", "a" * 40)
        self.stub_default_branch(self.http, "trunk")
        adapter = self.make_adapter()
        self.assertEqual(adapter.head_sha("main"), "a" * 40)
        self.assertEqual(adapter.default_branch(), "trunk")

    def test_is_ancestor_both_ways(self):
        self.stub_ancestry(self.http, "b" * 40, "c" * 40, True)
        self.stub_ancestry(self.http, "c" * 40, "b" * 40, False)
        adapter = self.make_adapter()
        self.assertTrue(adapter.is_ancestor("b" * 40, "c" * 40))
        self.assertFalse(adapter.is_ancestor("c" * 40, "b" * 40))

    def test_citation_url_needs_no_credential_and_marks_lines(self):
        adapter = self.make_adapter(token=None)
        plain = adapter.citation_url("project-data/hr/leave.md", "abc123")
        lined = adapter.citation_url("project-data/hr/leave.md", "abc123", (4, 9))
        for url in (plain, lined):
            self.assertIn("abc123", url)
            self.assertIn("leave.md", url)
            self.assertNotIn(TOKEN, url)
        self.assertNotEqual(plain, lined)

    def test_network_calls_need_a_credential(self):
        with self.assertRaises(AppError) as ctx:
            self.make_adapter(token=None).list_dir("")
        self.assertEqual(ctx.exception.status, 400)

    def test_http_failures_map_to_safe_app_errors(self):
        adapter = self.make_adapter()
        for code, expected in HTTP_ERRORS.items():
            with self.subTest(code=code):
                http = FakeHttp()
                http.fail_with_status(code)
                with http, self.assertRaises(AppError) as ctx:
                    adapter.list_dir("")
                self.assertEqual(ctx.exception.status, expected)
                self.assertNotIn(TOKEN, ctx.exception.message)
                self.assertNotIn("secret body", ctx.exception.message)

    def test_unreachable_host_is_a_502(self):
        import urllib.error
        http = FakeHttp()
        http.fail(urllib.error.URLError("dns"))
        with http, self.assertRaises(AppError) as ctx:
            self.make_adapter().list_dir("")
        self.assertEqual(ctx.exception.status, 502)

    def test_web_url_is_canonical_https_without_credentials(self):
        url = self.make_adapter().web_url
        self.assertTrue(url.startswith("https://"))
        self.assertNotIn("@", url)
        self.assertNotIn("?", url)
        self.assertNotIn(TOKEN, url)

    def test_verify_webhook_is_reserved(self):
        with self.assertRaises(AppError) as ctx:
            self.make_adapter().verify_webhook({}, b"")
        self.assertEqual(ctx.exception.status, 501)

    def test_clone_default_and_explicit_branch_without_leaking_the_token(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            bare = self._bare_repo_with_two_branches(Path(tmp))
            adapter = self.make_adapter()
            for branch, expected_branch in ((None, "main"), ("dev", "dev")):
                with self.subTest(branch=branch):
                    dest = Path(tmp) / f"clone-{branch}"
                    with mock.patch.object(type(adapter), "clone_url", new_callable=mock.PropertyMock,
                                           return_value=bare.as_uri()), \
                            mock.patch.object(git.subprocess, "run", wraps=subprocess.run) as run:
                        result = adapter.clone(dest, branch)
                    self.assertEqual(result.branch, expected_branch)
                    self.assertEqual(result.commit_sha, _git(bare, "rev-parse", expected_branch))
                    self.assertTrue((dest / "policies.md").is_file())
                    if branch:  # --single-branch: only the tracked branch is fetched
                        self.assertEqual(_git(dest, "branch", "-r", "--format=%(refname:short)").split(),
                                         [f"origin/{branch}"])
                    argv = " ".join(run.call_args_list[0].args[0])
                    self.assertNotIn(TOKEN, argv)
                    self.assertNotIn(TOKEN, (dest / ".git" / "config").read_text())
                    env = run.call_args_list[0].kwargs["env"]
                    self.assertIn("core.symlinks", env.values())

    @staticmethod
    def _bare_repo_with_two_branches(tmp: Path) -> Path:
        work, bare = tmp / "work", tmp / "bare.git"
        work.mkdir()
        _git(work, "init", "-b", "main")
        (work / "policies.md").write_text("# Policies\n")
        _git(work, "add", ".")
        _git(work, "commit", "-m", "one")
        _git(work, "checkout", "-b", "dev")
        (work / "extra.md").write_text("more\n")
        _git(work, "add", ".")
        _git(work, "commit", "-m", "two")
        _git(work, "checkout", "main")
        _git(tmp, "clone", "--bare", work.as_uri(), str(bare))
        return bare
