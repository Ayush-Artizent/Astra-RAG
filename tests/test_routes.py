import unittest
from contextlib import ExitStack, contextmanager
from unittest import mock

from fastapi.testclient import TestClient

from astra_rag import create_app
from astra_rag.services.cloner import CloneResult
from astra_rag.services.errors import AppError
from astra_rag.services.ingestion import pipeline
from astra_rag.services.registry import repos, runs
from astra_rag.services.sources.registry import parse_repo_url
from astra_rag.services.sync import service
from tests.helpers import use_temp_registry

FULL_ROOT = [
    {"name": "policies.md", "type": "file"}, {"name": "nomenclature.md", "type": "file"},
    {"name": "project-data", "type": "dir"}, {"name": "templates", "type": "dir"},
]
SLUG = "github.com__acme__golden"
SECRET = "ghp_route_test_secret"
CONNECT = "astra_rag.services.connections"
SYNC = "astra_rag.services.sync.service"


def fake_adapter(entries=FULL_ROOT, default="main", web_url="https://github.com/acme/golden"):
    adapter = mock.MagicMock()
    adapter.ref = parse_repo_url(web_url)
    adapter.list_dir.return_value = entries
    adapter.default_branch.return_value = default
    adapter.head_sha.return_value = "f" * 40
    adapter.web_url = web_url
    return adapter


@contextmanager
def fake_host(adapter, clone=None, clone_error=None, saved_token=None):
    """The host, the .env token store, the clone and the ingestion, faked for connect and the sync worker.

    The worker is not started in these tests, so a queued sync runs inline within the request.
    """
    tokens = {SLUG: saved_token} if saved_token else {}
    clone = clone or CloneResult("/tmp/x", "abc123", "main")
    with ExitStack() as stack:
        def patch(target, **kw):
            return stack.enter_context(mock.patch(target, **kw))

        adapter_for = patch(f"{CONNECT}.adapter_for", return_value=adapter)
        patch(f"{SYNC}.adapter_for", new=adapter_for)
        patch(f"{CONNECT}.token_store.get_token", side_effect=lambda ref, path=None: tokens.get(ref.slug))
        save = patch(f"{CONNECT}.token_store.save",
                     side_effect=lambda ref, url, token, path=None: tokens.__setitem__(ref.slug, token))
        clone_repo = patch(f"{SYNC}.cloner.clone_repo", return_value=clone, side_effect=clone_error)
        run = patch(f"{SYNC}.pipeline.run_ingestion")
        yield mock.Mock(adapter=adapter, adapter_for=adapter_for, clone_repo=clone_repo, save=save, run=run,
                        tokens=tokens)


class RouteTestBase(unittest.TestCase):
    def setUp(self):
        self.db_path = use_temp_registry(self)
        self.client = TestClient(create_app())
        self.body = {"url": "https://github.com/acme/golden", "token": SECRET}

    def connect(self, body=None, adapter=None, clone=None, clone_error=None, saved_token=None):
        """POST validate-and-clone with the host, clone, .env and ingestion faked out."""
        with fake_host(adapter or fake_adapter(), clone, clone_error, saved_token) as m:
            res = self.client.post("/api/validate-and-clone", json=body or self.body)
        return res, m

    def finish_latest(self, state="done"):
        runs.finish_run(runs.latest_run(SLUG)["run_id"], state)


class ConnectRouteTests(RouteTestBase):
    def test_connect_queues_a_background_sync_on_the_default_branch(self):
        res, m = self.connect()
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertNotIn("path", data)  # the server's clone folder is not the client's business
        self.assertEqual((data["branch"], data["commit_sha"]), ("main", "f" * 40))  # the head seen at connect
        self.assertEqual((data["ingestion"]["slug"], data["ingestion"]["state"]), (SLUG, "queued"))
        m.adapter.head_sha.assert_called_once_with("main")
        m.adapter.list_dir.assert_called_once_with("", ref="main")
        m.clone_repo.assert_called_once_with(m.adapter, "main")
        run_id, context, _path = m.run.call_args.args
        self.assertEqual(run_id, data["ingestion"]["run_id"])
        self.assertEqual((context.owner, context.name, context.branch, context.commit_sha),
                         ("acme", "golden", "main", "abc123"))
        self.assertEqual(m.save.call_args.args[1:], ("https://github.com/acme/golden", SECRET))

        status = self.client.get(f"/api/ingestion-status/{SLUG}").json()
        self.assertEqual((status["state"], status["branch"], status["commit_sha"], status["triggered_by"]),
                         ("queued", "main", "abc123", "connect"))
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["tracked_branch"], repo["index_state"]), ("main", "rebuilding"))

    def test_a_project_id_is_bound_to_the_repo_when_it_connects(self):
        res, _ = self.connect({**self.body, "project_id": " proj-1 "})
        self.assertEqual(res.json()["project_id"], "proj-1")
        self.assertEqual(repos.get_project("proj-1")["repo"]["slug"], SLUG)

    def test_no_project_id_binds_nothing(self):
        res, _ = self.connect()
        self.assertIsNone(res.json()["project_id"])
        self.assertIsNone(repos.get_project("proj-1"))

    def test_a_bad_project_id_is_rejected_before_the_host_is_called(self):
        res, m = self.connect({**self.body, "project_id": "bad id!"})
        self.assertEqual(res.status_code, 422)
        m.adapter.head_sha.assert_not_called()
        m.save.assert_not_called()
        self.assertIsNone(repos.get_repo(SLUG))

    def test_a_repo_that_fails_validation_binds_no_project(self):
        res, _ = self.connect({**self.body, "project_id": "proj-1"}, adapter=fake_adapter(entries=[]))
        self.assertEqual(res.status_code, 422)
        self.assertIsNone(repos.get_project("proj-1"))

    def test_connecting_again_with_another_project_keeps_both_bound(self):
        self.connect({**self.body, "project_id": "proj-1"})
        self.finish_latest()
        self.connect({**self.body, "project_id": "proj-2"})
        self.assertEqual(repos.get_project("proj-1")["repo"]["slug"], SLUG)
        self.assertEqual(repos.get_project("proj-2")["repo"]["slug"], SLUG)

    def test_explicit_branch_is_validated_cloned_and_tracked(self):
        res, m = self.connect({**self.body, "branch": " dev "}, clone=CloneResult("/tmp/x", "d" * 40, "dev"))
        self.assertEqual(res.json()["branch"], "dev")
        m.adapter.default_branch.assert_not_called()
        m.adapter.head_sha.assert_called_once_with("dev")
        m.clone_repo.assert_called_once_with(m.adapter, "dev")
        self.assertEqual(repos.tracked_branch(SLUG), "dev")

    def test_blank_branch_keeps_the_saved_tracked_branch(self):
        self.connect({**self.body, "branch": "dev"})
        self.finish_latest()
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
        self.assertEqual(res.status_code, 200)  # the clone runs in the background; its failure is on the run
        m.save.assert_called_once()
        m.run.assert_not_called()
        run = runs.latest_run(SLUG)
        self.assertEqual((run["state"], run["error"]), ("failed", "git clone failed."))
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["index_state"], repo["sync"]["source_error"]), ("none", "git clone failed."))

    def test_clone_failure_keeps_the_last_good_index(self):
        self.connect()
        self.finish_latest()
        good = repos.get_repo(SLUG)["indexed"]
        res, _ = self.connect(clone_error=RuntimeError("disk full"))
        self.assertNotIn("disk full", res.text)
        repo = repos.get_repo(SLUG)
        self.assertEqual(repo["last_run"]["error"], "Unexpected error while cloning.")
        self.assertNotIn("disk full", self.client.get("/api/repos").text)
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

    def test_second_connect_while_a_run_is_active_becomes_one_follow_up(self):
        self.connect()
        res, m = self.connect({**self.body, "branch": "dev"})
        data = res.json()
        self.assertEqual((res.status_code, data["ingestion"]["state"], data["ingestion"]["run_id"]),
                         (200, "pending", None))
        m.clone_repo.assert_not_called()
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["tracked_branch"], repo["sync"]["pending"]), ("dev", True))

        with fake_host(fake_adapter(), saved_token=SECRET) as m:  # the running sync ends; its follow-up starts
            self.finish_latest()
            service._follow_up(SLUG)
        m.clone_repo.assert_called_once_with(m.adapter, "dev")
        self.assertFalse(repos.get_repo(SLUG)["sync"]["pending"])

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
        with fake_host(adapter, saved_token=token) as m:
            res = self.client.put(f"/api/repos/{SLUG}/settings", json={"tracked_branch": branch})
        return res, m

    def test_repo_list_never_contains_the_token_or_its_location(self):
        self.connect()
        res = self.client.get("/api/repos")
        self.assertEqual([r["slug"] for r in res.json()["repos"]], [SLUG])
        for leak in (SECRET, "credential_ref", "env:", "_TOKEN"):
            self.assertNotIn(leak, res.text)

    def test_changing_the_branch_starts_a_rebuild_from_it(self):
        self.connect()
        self.finish_latest()
        self.assertFalse(repos.get_repo(SLUG)["needs_rebuild"])

        res, m = self.settings("dev")
        repo = res.json()["repo"]
        m.adapter.head_sha.assert_called_once_with("dev")
        m.clone_repo.assert_called_once_with(m.adapter, "dev")
        self.assertEqual((repo["tracked_branch"], repo["needs_rebuild"], repo["index_state"]),
                         ("dev", True, "rebuilding"))
        self.assertEqual(repo["indexed"]["branch"], "main")  # configured dev, still indexed (and served) at main
        self.assertEqual(runs.latest_run(SLUG)["triggered_by"], "settings")

        self.finish_latest()
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["indexed"]["branch"], repo["needs_rebuild"], repo["sync_status"]),
                         ("dev", False, "up_to_date"))

    def test_setting_the_same_branch_changes_nothing(self):
        self.connect()
        self.finish_latest()
        res, m = self.settings("main")
        m.adapter.head_sha.assert_not_called()
        m.clone_repo.assert_not_called()
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
        with TestClient(create_app()) as restarted:  # runs the lifespan: lock, migrate + sweep, worker
            listing = restarted.get("/api/repos").json()["repos"]
            status = restarted.get(f"/api/ingestion-status/{SLUG}").json()
        self.assertEqual([r["slug"] for r in listing], [SLUG])
        self.assertEqual((status["state"], status["error"]), ("failed", "Interrupted by a server restart."))
        res, m = self.connect()  # the swept run no longer blocks a new connect
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
