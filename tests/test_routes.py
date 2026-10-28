import unittest
from unittest import mock

from fastapi.testclient import TestClient

from astra_rag import create_app
from astra_rag.services.cloner import CloneResult
from astra_rag.services.errors import AppError
from astra_rag.services.ingestion import pipeline
from astra_rag.services.registry import repos, runs
from tests.helpers import use_temp_registry

FULL_ROOT = [
    {"name": "policies.md", "type": "file"}, {"name": "nomenclature.md", "type": "file"},
    {"name": "project-data", "type": "dir"}, {"name": "templates", "type": "dir"},
]
SLUG = "github.com__acme__golden"
SECRET = "ghp_route_test_secret"
CONNECT = "astra_rag.services.connections"


def fake_adapter(entries=FULL_ROOT, default="main", web_url="https://github.com/acme/golden"):
    adapter = mock.MagicMock()
    adapter.list_dir.return_value = entries
    adapter.default_branch.return_value = default
    adapter.head_sha.return_value = "f" * 40
    adapter.web_url = web_url
    return adapter


class RouteTestBase(unittest.TestCase):
    def setUp(self):
        self.db_path = use_temp_registry(self)
        self.client = TestClient(create_app())
        self.body = {"url": "https://github.com/acme/golden", "token": SECRET}

    def connect(self, body=None, adapter=None, clone=None, clone_error=None, saved_token=None):
        """POST validate-and-clone with the host, clone, .env and ingestion faked out."""
        adapter = adapter or fake_adapter()
        clone = clone or CloneResult("/tmp/x", "abc123", "main")
        with mock.patch(f"{CONNECT}.adapter_for", return_value=adapter) as adapter_for, \
                mock.patch(f"{CONNECT}.cloner.clone_repo", return_value=clone,
                           side_effect=clone_error) as clone_repo, \
                mock.patch(f"{CONNECT}.token_store.get_token", return_value=saved_token), \
                mock.patch(f"{CONNECT}.token_store.save") as save, \
                mock.patch("astra_rag.routes.pipeline.run_ingestion") as run:
            res = self.client.post("/api/validate-and-clone", json=body or self.body)
        return res, mock.Mock(adapter=adapter, adapter_for=adapter_for, clone_repo=clone_repo, save=save, run=run)


class ConnectRouteTests(RouteTestBase):
    def test_clone_queues_a_persisted_run_on_the_default_branch(self):
        res, m = self.connect()
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual((data["branch"], data["commit_sha"]), ("main", "abc123"))
        self.assertEqual(data["ingestion"]["slug"], SLUG)
        m.adapter.head_sha.assert_called_once_with("main")
        m.adapter.list_dir.assert_called_once_with("", ref="main")
        m.clone_repo.assert_called_once_with(m.adapter, "main")
        run_id, context, _path = m.run.call_args.args
        self.assertEqual(run_id, data["ingestion"]["run_id"])
        self.assertEqual((context.owner, context.name, context.branch, context.commit_sha),
                         ("acme", "golden", "main", "abc123"))
        self.assertEqual(m.save.call_args.args[1:], ("https://github.com/acme/golden", SECRET))

        status = self.client.get(f"/api/ingestion-status/{SLUG}").json()
        self.assertEqual((status["state"], status["branch"], status["commit_sha"]), ("queued", "main", "abc123"))
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["tracked_branch"], repo["index_state"]), ("main", "rebuilding"))

    def test_explicit_branch_is_validated_cloned_and_tracked(self):
        res, m = self.connect({**self.body, "branch": " dev "}, clone=CloneResult("/tmp/x", "d" * 40, "dev"))
        self.assertEqual(res.json()["branch"], "dev")
        m.adapter.default_branch.assert_not_called()
        m.adapter.head_sha.assert_called_once_with("dev")
        m.clone_repo.assert_called_once_with(m.adapter, "dev")
        self.assertEqual(repos.tracked_branch(SLUG), "dev")

    def test_blank_branch_keeps_the_saved_tracked_branch(self):
        self.connect({**self.body, "branch": "dev"})
        runs.finish_run(runs.latest_run(SLUG)["run_id"], "done")
        _, m = self.connect()
        m.adapter.default_branch.assert_not_called()
        m.clone_repo.assert_called_once_with(m.adapter, "dev")

    def test_unknown_branch_is_404_and_nothing_is_registered(self):
        adapter = fake_adapter()
        adapter.head_sha.side_effect = AppError("Branch not found in the repository.", 404)
        res, m = self.connect({**self.body, "branch": "nope"}, adapter=adapter)
        self.assertEqual(res.status_code, 404)
        m.clone_repo.assert_not_called()
        self.assertIsNone(repos.get_repo(SLUG))

    def test_branch_names_that_could_be_git_options_are_rejected_before_any_host_call(self):
        for bad in ("-x", "--upload-pack=evil", "a..b", "a b", "/a", "a/", "a.lock", "x" * 201):
            with self.subTest(branch=bad):
                res, m = self.connect({**self.body, "branch": bad})
                self.assertEqual(res.status_code, 400)
                m.adapter_for.assert_not_called()

    def test_blank_token_reuses_saved_one_and_does_not_rewrite_it(self):
        res, m = self.connect({**self.body, "token": ""}, saved_token="saved-secret")
        data = res.json()
        self.assertTrue(data["ok"] and data["token_reused"] and not data["token_saved"])
        self.assertEqual(m.adapter_for.call_args.args[1].secret(), "saved-secret")
        m.save.assert_not_called()
        self.assertNotIn("saved-secret", res.text)

    def test_no_typed_and_no_saved_token_is_rejected(self):
        res, _ = self.connect({**self.body, "token": " "})
        self.assertEqual(res.status_code, 400)

    def test_clone_failure_is_a_failed_run_and_the_token_is_still_saved(self):
        res, m = self.connect(clone_error=AppError("git clone failed.", 502))
        self.assertEqual(res.status_code, 502)
        m.save.assert_called_once()
        m.run.assert_not_called()
        run = runs.latest_run(SLUG)
        self.assertEqual((run["state"], run["error"]), ("failed", "git clone failed."))
        self.assertEqual(repos.get_repo(SLUG)["index_state"], "none")

    def test_clone_failure_keeps_the_last_good_index(self):
        self.connect()
        runs.finish_run(runs.latest_run(SLUG)["run_id"], "done")
        good = repos.get_repo(SLUG)["indexed"]
        self.client = TestClient(create_app(), raise_server_exceptions=False)
        res, _ = self.connect(clone_error=RuntimeError("disk full"))
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("disk full", res.text)
        repo = repos.get_repo(SLUG)
        self.assertEqual(repo["last_run"]["error"], "Unexpected error while cloning.")
        self.assertEqual(repo["indexed"], good)
        self.assertEqual(repo["index_state"], "ready")  # the clone failed before Qdrant was touched

    def test_rejected_token_is_not_saved(self):
        adapter = fake_adapter()
        adapter.default_branch.side_effect = AppError("rejected the token", 401)
        res, m = self.connect(adapter=adapter)
        self.assertEqual(res.status_code, 401)
        m.save.assert_not_called()

    def test_missing_structure_saves_the_token_but_registers_and_queues_nothing(self):
        res, m = self.connect(adapter=fake_adapter(FULL_ROOT[:2]))
        self.assertEqual(res.status_code, 422)
        self.assertTrue(res.json()["token_saved"])
        self.assertEqual(res.json()["missing"], ["project-data/", "templates/"])
        m.save.assert_called_once()
        self.assertIsNone(repos.get_repo(SLUG))
        self.assertIsNone(runs.latest_run(SLUG))

    def test_second_connect_while_a_run_is_active_is_409_and_does_not_clone(self):
        self.connect()
        res, m = self.connect({**self.body, "branch": "dev"})
        self.assertEqual(res.status_code, 409)
        m.clone_repo.assert_not_called()
        self.assertEqual(repos.tracked_branch(SLUG), "main")  # the refused request changed nothing

    def test_typed_url_is_stored_cleaned_and_never_echoed(self):
        body = {**self.body, "url": "https://someone:hunter2@github.com/acme/golden.git?tab=x#frag"}
        res, m = self.connect(body)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(repos.get_repo(SLUG)["url"], "https://github.com/acme/golden")
        self.assertEqual(m.save.call_args.args[1], "https://github.com/acme/golden")
        listing = self.client.get("/api/repos").text
        for text in (res.text, listing):
            self.assertNotIn("hunter2", text)
            self.assertNotIn("tab=x", text)

    def test_bad_url_errors_do_not_echo_the_url(self):
        for url in ("ftp://u:hunter2@github.com/a/b", "https://u:hunter2@github.com/",
                    "https://u:hunter2@gitlab.com/a/b"):
            with self.subTest(url=url):
                res = self.client.post("/api/validate-and-clone", json={"url": url, "token": "t"})
                self.assertEqual(res.status_code, 400)
                self.assertNotIn("hunter2", res.text)

    def test_status_404_when_unknown(self):
        res = self.client.get("/api/ingestion-status/github.com__nobody__nothing")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.json()["ok"])

    def test_search_requires_query(self):
        with mock.patch.object(pipeline, "QdrantStore"):
            res = self.client.post("/api/search", json={"slug": "github.com__a__b", "query": " "})
        self.assertEqual(res.status_code, 400)


class RepoAndProjectRouteTests(RouteTestBase):
    def settings(self, branch, token="saved", head_error=None):
        adapter = fake_adapter()
        adapter.head_sha.side_effect = head_error
        with mock.patch(f"{CONNECT}.token_store.get_token", return_value=token), \
                mock.patch(f"{CONNECT}.adapter_for", return_value=adapter):
            res = self.client.put(f"/api/repos/{SLUG}/settings", json={"tracked_branch": branch})
        return res, adapter

    def test_repo_list_never_contains_the_token_or_its_location(self):
        self.connect()
        res = self.client.get("/api/repos")
        self.assertEqual([r["slug"] for r in res.json()["repos"]], [SLUG])
        for leak in (SECRET, "credential_ref", "env:", "_TOKEN"):
            self.assertNotIn(leak, res.text)

    def test_changing_the_branch_marks_a_rebuild_and_the_next_connect_uses_it(self):
        self.connect()
        runs.finish_run(runs.latest_run(SLUG)["run_id"], "done")
        self.assertFalse(repos.get_repo(SLUG)["needs_rebuild"])

        res, adapter = self.settings("dev")
        repo = res.json()["repo"]
        adapter.head_sha.assert_called_once_with("dev")
        self.assertEqual((repo["tracked_branch"], repo["needs_rebuild"]), ("dev", True))
        self.assertEqual(repo["indexed"]["branch"], "main")  # configured dev, still indexed at main

        _, m = self.connect()
        m.clone_repo.assert_called_once_with(m.adapter, "dev")
        runs.finish_run(runs.latest_run(SLUG)["run_id"], "done")
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["indexed"]["branch"], repo["needs_rebuild"]), ("dev", False))

    def test_setting_the_same_branch_changes_nothing(self):
        self.connect()
        runs.finish_run(runs.latest_run(SLUG)["run_id"], "done")
        res, adapter = self.settings("main")
        adapter.head_sha.assert_not_called()
        self.assertFalse(res.json()["repo"]["needs_rebuild"])

    def test_settings_errors(self):
        res, _ = self.settings("dev")
        self.assertEqual(res.status_code, 404)  # not registered
        self.connect()
        res, _ = self.settings("dev", token=None)
        self.assertEqual(res.status_code, 400)
        res, _ = self.settings("gone", head_error=AppError("Branch not found in the repository.", 404))
        self.assertEqual(res.status_code, 404)
        res, _ = self.settings("--bad")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(repos.tracked_branch(SLUG), "main")

    def test_project_binding_routes(self):
        self.connect()
        res = self.client.put("/api/projects/proj-1/binding", json={"repo_slug": SLUG})
        self.assertEqual(res.json()["project"]["repo"]["slug"], SLUG)
        got = self.client.get("/api/projects/proj-1").json()["project"]
        self.assertEqual(got["repo"]["projects"], ["proj-1"])

        res = self.client.put("/api/projects/proj-1/binding", json={"repo_slug": "github.com__no__repo"})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.client.get("/api/projects/proj-1").json()["project"]["repo"]["slug"], SLUG)

        self.assertEqual(self.client.get("/api/projects/unbound").status_code, 404)
        self.assertEqual(self.client.put("/api/projects/bad id!/binding", json={"repo_slug": SLUG}).status_code, 422)

    def test_repos_and_status_survive_a_restart(self):
        self.connect()
        with TestClient(create_app()) as restarted:  # runs the lifespan: migrate + sweep
            listing = restarted.get("/api/repos").json()["repos"]
            status = restarted.get(f"/api/ingestion-status/{SLUG}").json()
        self.assertEqual([r["slug"] for r in listing], [SLUG])
        self.assertEqual((status["state"], status["error"]), ("failed", "Interrupted by a server restart."))
        res, m = self.connect()  # the swept run no longer blocks a new connect
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
