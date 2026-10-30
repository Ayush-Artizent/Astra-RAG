import tempfile
import threading
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from astra_rag import create_app
from astra_rag.services.cloner import CloneResult
from astra_rag.services.errors import AppError
from astra_rag.services.local_models import ModelsNotReady
from astra_rag.services.ingestion import pipeline
from astra_rag.services.ingestion.store import QdrantStore, collection_name, version_name
from astra_rag.services.registry import repos, runs
from astra_rag.services.sources.registry import parse_repo_url
from astra_rag.services.sync import reconcile, scheduler, service
from astra_rag.services.sync.instance import InstanceLock
from tests.helpers import use_temp_registry
from tests.test_ingestion import FIXTURE_REPO, FakeEmbedder

URL = "https://github.com/acme/golden"
REF = parse_repo_url(URL)
SLUG = REF.slug
SECRET = "ghp_sync_test_secret"
SYNC = "astra_rag.services.sync.service"
OLD, NEW = "a" * 40, "b" * 40


class SyncTestBase(unittest.TestCase):
    """The real sync service and pipeline on in-memory Qdrant; only the host, .env and git are faked."""

    def setUp(self):
        use_temp_registry(self)
        self.store = QdrantStore(QdrantClient(":memory:"))
        self.embedder = FakeEmbedder()
        self.head = OLD
        self.adapter = mock.MagicMock()
        self.adapter.ref = REF
        self.adapter.head_sha.side_effect = lambda branch: self.head
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch(f"{SYNC}.adapter_for", return_value=self.adapter))
        self.token = stack.enter_context(mock.patch(f"{SYNC}.token_store.get_token", return_value=SECRET))
        self.clone = stack.enter_context(mock.patch(
            f"{SYNC}.cloner.clone_repo", side_effect=lambda adapter, branch: CloneResult(
                str(FIXTURE_REPO), self.head, branch)))
        stack.enter_context(mock.patch.object(pipeline, "QdrantStore", return_value=self.store))
        stack.enter_context(mock.patch.object(pipeline, "get_embedder", return_value=self.embedder))

    def connect(self, branch="main"):
        """What connect leaves behind: a registered repo and a forced run, then the worker runs it (inline)."""
        run_id = runs.register_and_queue(REF, URL, branch, "env:X_TOKEN")
        if run_id is not None:
            service.start(run_id)
        return run_id

    def search(self):
        return pipeline.search(SLUG, "annual leave", embedder=self.embedder, store=self.store)

    def run_count(self):
        from astra_rag.services.registry import db
        with db.transaction(write=False) as conn:
            return conn.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]


class SyncServiceTests(SyncTestBase):
    def test_the_clone_is_removed_after_a_successful_run(self):
        with mock.patch(f"{SYNC}.cloner.remove_clone") as remove:
            self.connect()
        remove.assert_called_once_with(SLUG)
        self.assertEqual(runs.latest_run(SLUG)["state"], "done")

    def test_the_clone_is_removed_even_when_ingestion_blows_up(self):
        run_id = runs.register_and_queue(REF, URL, "main", "env:X_TOKEN")
        with mock.patch(f"{SYNC}.cloner.remove_clone") as remove, \
                mock.patch(f"{SYNC}.pipeline.run_ingestion", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service.execute(run_id)
        remove.assert_called_once_with(SLUG)

    def test_a_failed_clone_leaves_no_partial_folder(self):
        self.clone.side_effect = AppError("The host refused the clone.")
        with mock.patch(f"{SYNC}.cloner.remove_clone") as remove:
            self.connect()
        remove.assert_called_once_with(SLUG)
        self.assertEqual(runs.latest_run(SLUG)["state"], "failed")

    def test_a_run_fails_cleanly_when_the_models_cannot_be_prepared(self):
        with mock.patch(f"{SYNC}.local_models.wait_ready", side_effect=ModelsNotReady("Models are not ready.")):
            self.connect()
        run = runs.latest_run(SLUG)
        self.assertEqual((run["state"], run["error"]), ("failed", "Models are not ready."))
        self.clone.assert_not_called()  # nothing is cloned for a run that cannot embed

    def test_a_run_waits_for_the_embedder_model_before_cloning(self):
        order = []
        self.clone.side_effect = lambda adapter, branch: order.append("clone") or CloneResult(
            str(FIXTURE_REPO), self.head, branch)
        with mock.patch(f"{SYNC}.local_models.wait_ready", side_effect=lambda names: order.append(("wait", names))):
            self.connect()
        self.assertEqual(order[:2], [("wait", ("embedder",)), "clone"])

    def test_unchanged_head_runs_nothing_and_records_the_check(self):
        self.connect()
        before = self.run_count()
        result = service.request_sync(SLUG, "manual")
        self.assertEqual(result, {"state": "up_to_date", "commit_sha": OLD})
        self.assertEqual(self.run_count(), before)
        self.assertEqual(self.clone.call_count, 1)
        repo = repos.get_repo(SLUG)
        self.assertTrue(repo["sync"]["last_checked_at"])
        self.assertEqual(repo["sync_status"], "up_to_date")

    def test_changed_head_builds_a_new_version_and_swaps_the_alias(self):
        first = self.connect()
        self.head = NEW
        result = service.request_sync(SLUG, "manual")
        self.assertEqual(result["state"], "queued")
        second = result["run_id"]
        alias = collection_name(SLUG)
        self.assertEqual(self.store.alias_target(alias), version_name(SLUG, second))
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, second)])
        self.assertNotIn(version_name(SLUG, first), self.store.collections())
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["indexed"]["commit_sha"], repo["indexed"]["run_id"]), (NEW, second))
        self.assertTrue(all(NEW in hit["source_url"] for hit in self.search()))
        self.assertEqual(runs.latest_run(SLUG)["triggered_by"], "manual")

    def test_a_branch_change_rebuilds_even_when_the_head_is_unchanged(self):
        self.connect()
        repos.set_tracked_branch(SLUG, "dev")
        self.assertEqual(service.request_sync(SLUG, "nightly")["state"], "queued")
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["indexed"]["branch"], repo["needs_rebuild"]), ("dev", False))

    def test_config_version_is_stable_so_nightly_checks_stop_rebuilding(self):
        self.connect()
        for trigger, force in (("manual", False), ("nightly", False), ("follow_up", True)):
            if force:
                service.request_sync(SLUG, trigger, force=True)
            else:
                self.head = NEW if self.head == OLD else OLD
                self.assertEqual(service.request_sync(SLUG, trigger)["state"], "queued")
        self.assertFalse(repos.get_repo(SLUG)["needs_rebuild"])
        before = self.run_count()
        self.assertEqual(service.request_sync(SLUG, "nightly")["state"], "up_to_date")
        self.assertEqual(self.run_count(), before)

    def test_triggers_during_a_run_coalesce_into_one_follow_up(self):
        started, release, results = threading.Event(), threading.Event(), []
        real_run = pipeline.run_ingestion

        def slow_run(*args, **kwargs):
            if not started.is_set():
                started.set()
                release.wait(5)
            real_run(*args, **kwargs)

        with mock.patch(f"{SYNC}.pipeline.run_ingestion", side_effect=slow_run):
            worker_thread = threading.Thread(target=self.connect)
            worker_thread.start()
            self.assertTrue(started.wait(5))
            self.head = NEW
            barrier = threading.Barrier(6)

            def trigger():
                barrier.wait()
                results.append(service.request_sync(SLUG, "manual")["state"])

            threads = [threading.Thread(target=trigger) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            release.set()
            worker_thread.join(10)
        self.assertEqual(results, ["pending"] * 6)
        self.assertEqual(self.run_count(), 2)  # the connect run plus exactly one follow-up
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["indexed"]["commit_sha"], repo["sync"]["pending"]), (NEW, False))

    def test_a_failed_sync_keeps_the_old_index_serving(self):
        good = self.connect()
        self.head = NEW
        with mock.patch.object(self.embedder, "embed_passages", side_effect=RuntimeError("model crashed")):
            service.request_sync(SLUG, "manual")
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["last_run"]["state"], repo["index_state"]), ("failed", "ready"))
        self.assertEqual(repo["indexed"]["run_id"], good)
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, good)])
        self.assertTrue(self.search())

    def test_a_revoked_token_sets_source_error_and_search_still_works(self):
        self.connect()
        self.adapter.head_sha.side_effect = AppError("The host rejected the token.", 401)
        with self.assertRaises(AppError):
            service.request_sync(SLUG, "manual")
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["sync_status"], repo["sync"]["source_error"]), ("source_error", service.REJECTED))
        self.assertTrue(self.search())
        self.adapter.head_sha.side_effect = lambda branch: self.head
        service.request_sync(SLUG, "manual")
        self.assertEqual(repos.get_repo(SLUG)["sync"]["source_error"], "")

    def test_no_saved_token_is_a_source_error(self):
        self.connect()
        self.token.return_value = None
        with self.assertRaises(AppError) as ctx:
            service.request_sync(SLUG, "manual")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(repos.get_repo(SLUG)["sync"]["source_error"], service.NO_TOKEN)

    def test_unknown_repo_is_404(self):
        with self.assertRaises(AppError) as ctx:
            service.request_sync("github.com__no__repo", "manual")
        self.assertEqual(ctx.exception.status, 404)

    def test_errors_and_logs_never_contain_the_token(self):
        self.connect()
        self.adapter.head_sha.side_effect = AppError("The host rejected the token.", 401)
        with self.assertLogs("astra_rag", level="WARNING") as logs:
            scheduler.run_pass([SLUG], "nightly")
        self.clone.side_effect = RuntimeError(f"boom {SECRET}")
        with self.assertLogs("astra_rag", level="WARNING") as clone_logs:
            service.request_sync(SLUG, "manual", force=True)
        client = TestClient(create_app())
        texts = [repr(repos.get_repo(SLUG)), repr(runs.latest_run(SLUG)), client.get("/api/repos").text,
                 *logs.output, *clone_logs.output]
        for text in texts:
            self.assertNotIn(SECRET, text)
            self.assertNotIn("boom", text)


class SyncRouteTests(SyncTestBase):
    def test_sync_now_route(self):
        client = TestClient(create_app())
        self.assertEqual(client.post("/api/repos/github.com__no__repo/sync").status_code, 404)
        self.connect()
        self.assertEqual(client.post(f"/api/repos/{SLUG}/sync").json()["state"], "up_to_date")
        self.head = NEW
        data = client.post(f"/api/repos/{SLUG}/sync").json()
        self.assertEqual((data["ok"], data["state"]), (True, "queued"))
        listing = client.get("/api/repos").json()
        self.assertEqual(listing["repos"][0]["indexed"]["commit_sha"], NEW)
        self.assertEqual(listing["schedule"]["daily_at_utc"], "02:00")
        self.head = OLD
        with mock.patch(f"{SYNC}.runs.queue_run", return_value=None):
            self.assertEqual(client.post(f"/api/repos/{SLUG}/sync").json()["state"], "pending")


class ReconcileTests(SyncTestBase):
    def crash_after_swap(self):
        """A sync whose process died after the alias switch but before the run was recorded as done."""
        self.connect()
        self.head = NEW
        with mock.patch.object(runs, "finish_run"):  # the record of success never happens
            run_id = service.request_sync(SLUG, "manual")["run_id"]
        runs.sweep_interrupted()  # what the restart does first
        return run_id

    def test_a_completed_swap_is_adopted(self):
        run_id = self.crash_after_swap()
        self.assertEqual(repos.get_repo(SLUG)["indexed"]["commit_sha"], OLD)
        reconcile.run(self.store)
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["indexed"]["run_id"], repo["indexed"]["commit_sha"]), (run_id, NEW))
        self.assertEqual(repo["last_run"]["error"], runs.RECOVERED_NOTE)
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, run_id)])  # the old one is dropped

    def test_an_unknown_alias_target_keeps_serving_and_asks_for_a_rebuild(self):
        self.connect()
        stray = version_name(SLUG, 999)
        self.store.create(stray, self.embedder.dense_dim)
        self.store.swap_alias(collection_name(SLUG), stray)
        reconcile.run(self.store)
        repo = repos.get_repo(SLUG)
        self.assertEqual(self.store.alias_target(collection_name(SLUG)), stray)
        self.assertEqual((repo["sync"]["pending"], repo["sync_status"]), (True, "pending"))
        self.assertEqual(runs.take_pending(SLUG), (True, True))

    def test_orphans_are_dropped_but_never_the_live_version_or_an_active_run(self):
        good = self.connect()
        orphan = version_name(SLUG, good + 50)
        self.store.create(orphan, self.embedder.dense_dim)
        reconcile.run(self.store)
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, good)])

        active = runs.queue_run(SLUG, "manual", force=True)  # a run in progress owns its new version
        self.store.create(version_name(SLUG, active), self.embedder.dense_dim)
        reconcile.run(self.store)
        self.assertIn(version_name(SLUG, active), self.store.versions(SLUG))

    def test_a_missing_index_asks_for_a_rebuild(self):
        self.connect()
        self.store.client.delete_collection(self.store.alias_target(collection_name(SLUG)))
        reconcile.run(self.store)
        self.assertTrue(repos.get_repo(SLUG)["sync"]["pending"])

    def test_qdrant_down_is_skipped_without_error(self):
        class Down(QdrantStore):
            def ping(self):
                raise AppError("Could not reach Qdrant.", 503)

        self.connect()
        with self.assertLogs("astra_rag", level="WARNING"):
            reconcile.run(Down(QdrantClient(":memory:")))


class InstanceLockTests(unittest.TestCase):
    def test_only_one_instance_per_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = InstanceLock(Path(tmp) / "astra.lock"), InstanceLock(Path(tmp) / "astra.lock")
            first.acquire()
            try:
                with self.assertRaises(AppError) as ctx:
                    second.acquire()
                self.assertIn("Another Astra-RAG instance", ctx.exception.message)
            finally:
                first.release()
            second.acquire()  # free again once the first instance is gone
            second.release()


class SchedulerTests(unittest.TestCase):
    def test_next_run_at(self):
        at = lambda h, m: datetime(2026, 10, 28, h, m, tzinfo=timezone.utc)
        self.assertEqual(scheduler.next_run_at(at(1, 0), "02:00"), at(2, 0))
        self.assertEqual(scheduler.next_run_at(at(2, 0), "02:00"), datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(scheduler.next_run_at(at(23, 30), "00:15"),
                         datetime(2026, 10, 29, 0, 15, tzinfo=timezone.utc))

    def test_bad_time_settings_are_rejected(self):
        for bad in ("2:00", "24:00", "02:60", "2am", ""):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                scheduler.parse_daily_at(bad)

    def test_a_pass_checks_every_repo_and_one_failure_does_not_stop_the_others(self):
        calls = []

        def fake_request(slug, trigger, force=False):
            calls.append((slug, trigger, force))
            if slug == "a":
                raise AppError("The host rejected the token.", 401)

        with mock.patch.object(scheduler, "request_sync", side_effect=fake_request), \
                mock.patch.object(scheduler.runs, "take_pending", side_effect=[(False, False), (True, True)]):
            scheduler.run_pass(["a", "b"], "nightly")
        self.assertEqual(calls, [("a", "nightly", False), ("b", "nightly", True)])

    def test_the_thread_starts_with_a_catch_up_and_stops_on_request(self):
        with mock.patch.object(scheduler.repos, "due_slugs", return_value=[]) as due, \
                mock.patch.object(scheduler, "_seconds_until_next", return_value=3600):
            scheduler.start()
            try:
                self.assertTrue(scheduler.schedule()["enabled"])
                self.assertTrue(scheduler.schedule()["next_check_at"])
            finally:
                scheduler.stop()
        due.assert_called_once()
        self.assertFalse(scheduler.schedule()["enabled"])


if __name__ == "__main__":
    unittest.main()
