import sqlite3
import threading
import unittest
from contextlib import closing
from unittest import mock

from astra_rag.services.errors import AppError
from astra_rag.services.registry import db, repos, runs, startup
from astra_rag.services.registry.rules import check_branch_name, check_project_id
from astra_rag.services.sources.registry import parse_repo_url
from tests.helpers import use_temp_registry

REF = parse_repo_url("https://github.com/acme/golden")
OTHER = parse_repo_url("https://dev.azure.com/org/proj/_git/golden")
URL = "https://github.com/acme/golden"


def queue(ref=REF, branch="main") -> int | None:
    return runs.register_and_queue(ref, URL, branch, "env:X_TOKEN")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.path = use_temp_registry(self)

    def version(self) -> int:
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def tables(self) -> set[str]:
        with closing(sqlite3.connect(self.path)) as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def test_fresh_database_gets_the_current_schema_and_rerunning_is_harmless(self):
        db.migrate()
        db.migrate()
        self.assertEqual(self.version(), db.schema_version())
        self.assertTrue({"repos", "project_bindings", "ingestion_runs"} <= self.tables())

    def test_a_newer_database_is_refused_and_left_untouched(self):
        db.migrate()
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(AppError) as ctx:
            db.migrate()
        self.assertIn("newer", ctx.exception.message)
        self.assertEqual(self.version(), 99)

    def test_a_failing_migration_rolls_back_completely(self):
        db.migrate()
        broken = db.MIGRATIONS + (("CREATE TABLE half_done (x INTEGER)", "THIS IS NOT SQL"),)
        with mock.patch.object(db, "MIGRATIONS", broken), self.assertRaises(sqlite3.Error):
            db.migrate()
        self.assertEqual(self.version(), db.schema_version())
        self.assertNotIn("half_done", self.tables())

    def test_the_first_use_migrates_lazily(self):
        self.assertEqual(repos.list_repos(), [])
        self.assertEqual(self.version(), db.schema_version())

    def test_upgrading_from_schema_1_keeps_existing_rows(self):
        with mock.patch.object(db, "MIGRATIONS", db.MIGRATIONS[:1]):
            db.migrate()
            with db.transaction() as conn:
                conn.execute("INSERT INTO repos (slug, url, host_kind, host, tracked_branch, credential_ref,"
                             " created_at, updated_at) VALUES ('s', 'u', 'github', 'h', 'main', 'env:X', 'n', 'n')")
                conn.execute("INSERT INTO ingestion_runs (repo_slug, state, branch, config_version, queued_at)"
                             " VALUES ('s', 'done', 'main', 1, 'n')")
        self.assertEqual(self.version(), 1)
        db._ready.clear()
        db.migrate()
        self.assertEqual(self.version(), db.schema_version())
        repo = repos.get_repo("s")
        self.assertEqual((repo["tracked_branch"], repo["sync"]),
                         ("main", {"last_checked_at": None, "pending": False, "source_error": ""}))
        self.assertEqual(runs.latest_run("s")["triggered_by"], "connect")

    def test_foreign_keys_are_enforced_on_every_connection(self):
        with self.assertRaises(sqlite3.IntegrityError), db.transaction() as conn:
            conn.execute("INSERT INTO project_bindings VALUES ('p', 'no-such-repo', 'now')")


class RepoAndBindingTests(unittest.TestCase):
    def setUp(self):
        use_temp_registry(self)

    def test_queueing_registers_the_repo_without_the_token(self):
        queue()
        repo = repos.get_repo(REF.slug)
        self.assertEqual((repo["url"], repo["host_kind"], repo["tracked_branch"]), (URL, "github", "main"))
        self.assertNotIn("credential_ref", repo)
        self.assertEqual([r["slug"] for r in repos.list_repos()], [REF.slug])
        self.assertIsNone(repos.get_repo("missing"))
        self.assertIsNone(repos.tracked_branch("missing"))

    def test_set_tracked_branch(self):
        queue()
        runs.finish_run(runs.latest_run(REF.slug)["run_id"], "done")
        repos.set_tracked_branch(REF.slug, "main")
        self.assertFalse(repos.get_repo(REF.slug)["needs_rebuild"])
        repos.set_tracked_branch(REF.slug, "dev")
        self.assertTrue(repos.get_repo(REF.slug)["needs_rebuild"])
        with self.assertRaises(AppError) as ctx:
            repos.set_tracked_branch("missing", "dev")
        self.assertEqual(ctx.exception.status, 404)

    def test_one_repo_per_project_and_one_repo_serves_many_projects(self):
        queue()
        queue(OTHER)
        repos.bind_project("a", REF.slug)
        repos.bind_project("b", REF.slug)
        self.assertEqual(repos.get_repo(REF.slug)["projects"], ["a", "b"])
        repos.bind_project("a", OTHER.slug)  # rebinding replaces
        self.assertEqual(repos.get_project("a")["repo"]["slug"], OTHER.slug)
        self.assertEqual(repos.get_repo(REF.slug)["projects"], ["b"])
        self.assertIsNone(repos.get_project("nobody"))

    def test_a_failed_rebind_keeps_the_old_binding(self):
        queue()
        repos.bind_project("a", REF.slug)
        with self.assertRaises(AppError) as ctx:
            repos.bind_project("a", "github.com__no__repo")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(repos.get_project("a")["repo"]["slug"], REF.slug)


class RunLifecycleTests(unittest.TestCase):
    def setUp(self):
        use_temp_registry(self)

    def test_done_run_becomes_the_indexed_build(self):
        run_id = queue()
        runs.update_run(run_id, state="running", commit_sha="abc", files_skipped=[{"path": "x", "reason": "y"}])
        runs.finish_run(run_id, "done", chunks_total=3, chunks_stored=3, warnings=["w"])
        repo = repos.get_repo(REF.slug)
        self.assertEqual((repo["index_state"], repo["needs_rebuild"]), ("ready", False))
        self.assertEqual((repo["indexed"]["run_id"], repo["indexed"]["branch"], repo["indexed"]["commit_sha"]),
                         (run_id, "main", "abc"))
        status = runs.latest_run(REF.slug)
        self.assertEqual((status["state"], status["chunks_stored"], status["warnings"]), ("done", 3, ["w"]))
        self.assertEqual(status["files_skipped"], [{"path": "x", "reason": "y"}])
        self.assertTrue(status["finished_at"])

    def test_a_failed_run_never_overwrites_the_last_good_build(self):
        good = queue()
        runs.update_run(good, commit_sha="good")
        runs.finish_run(good, "done")
        before = repos.get_repo(REF.slug)["indexed"]

        failed = queue()  # failed before touching Qdrant (e.g. ping): the old index still serves
        runs.update_run(failed, commit_sha="new")
        runs.finish_run(failed, "failed", error="Could not reach Qdrant.")
        repo = repos.get_repo(REF.slug)
        self.assertEqual((repo["indexed"], repo["index_state"]), (before, "ready"))

        broken = queue()  # failed after the collection was dropped: search may be partial
        runs.update_run(broken, index_replaced=1)
        runs.finish_run(broken, "failed", error="boom")
        repo = repos.get_repo(REF.slug)
        self.assertEqual(repo["indexed"], before)
        self.assertEqual((repo["index_state"], repo["needs_rebuild"]), ("incomplete", True))
        self.assertEqual(repo["last_run"]["error"], "boom")

        later = queue()  # a later clone failure does not make the dropped index whole again
        runs.finish_run(later, "failed", error="clone")
        self.assertEqual(repos.get_repo(REF.slug)["index_state"], "incomplete")

    def test_branch_change_during_a_run_keeps_needs_rebuild_after_it_succeeds(self):
        run_id = queue()
        repos.set_tracked_branch(REF.slug, "dev")
        runs.finish_run(run_id, "done")
        repo = repos.get_repo(REF.slug)
        self.assertEqual((repo["tracked_branch"], repo["indexed"]["branch"]), ("dev", "main"))
        self.assertTrue(repo["needs_rebuild"])

    def test_an_older_run_finishing_late_does_not_replace_a_newer_build(self):
        older = queue()
        with db.transaction() as conn:  # a second active run, as if another process skipped the guard
            newer = conn.execute("INSERT INTO ingestion_runs (repo_slug, state, branch, config_version, queued_at)"
                                 " VALUES (?, 'running', 'main', 1, 'now')", (REF.slug,)).lastrowid
        runs.finish_run(newer, "done")
        runs.finish_run(older, "done")
        repo = repos.get_repo(REF.slug)
        self.assertEqual(repo["indexed"]["run_id"], newer)
        self.assertEqual(runs.latest_run(REF.slug)["run_id"], newer)

    def test_finished_or_swept_runs_ignore_late_updates(self):
        run_id = queue()
        self.assertEqual(runs.sweep_interrupted(), 1)
        runs.update_run(run_id, chunks_stored=5)
        runs.finish_run(run_id, "done")
        status = runs.latest_run(REF.slug)
        self.assertEqual((status["state"], status["chunks_stored"]), ("failed", 0))
        self.assertEqual(status["error"], "Interrupted by a server restart.")
        self.assertIsNone(repos.get_repo(REF.slug)["indexed"])

    def test_startup_sweeps_interrupted_runs(self):
        queue()
        startup()
        self.assertEqual(runs.latest_run(REF.slug)["state"], "failed")
        queue()  # no longer blocked

    def test_one_active_run_per_repo_and_later_triggers_coalesce(self):
        first = queue()
        self.assertIsNone(queue(branch="dev"))  # coalesced: no second run, a forced follow-up instead
        repo = repos.get_repo(REF.slug)
        self.assertEqual((repo["tracked_branch"], repo["sync"]["pending"], repo["sync_status"]),
                         ("dev", True, "queued"))
        self.assertIsNone(runs.queue_run(REF.slug, "manual"))
        self.assertIsNotNone(queue(OTHER))  # other repos are not blocked
        runs.finish_run(first, "failed")
        self.assertEqual(repos.get_repo(REF.slug)["sync_status"], "pending")
        self.assertEqual(runs.take_pending(REF.slug), (True, True))
        self.assertEqual(runs.take_pending(REF.slug), (False, False))  # read and cleared once
        self.assertIsNotNone(runs.queue_run(REF.slug, "follow_up", force=True))

    def test_a_new_run_satisfies_a_waiting_follow_up(self):
        first = queue()
        runs.queue_run(REF.slug, "manual")
        runs.finish_run(first, "done")
        runs.queue_run(REF.slug, "manual")  # claimed before the follow-up was taken
        self.assertEqual(runs.take_pending(REF.slug), (False, False))

    def test_unregistered_repo_cannot_be_queued(self):
        with self.assertRaises(AppError) as ctx:
            runs.queue_run("github.com__no__repo", "manual")
        self.assertEqual(ctx.exception.status, 404)

    def test_config_version_changes_only_with_the_tracked_branch(self):
        def version():
            with db.transaction(write=False) as conn:
                return conn.execute("SELECT config_version FROM repos WHERE slug = ?", (REF.slug,)).fetchone()[0]

        runs.finish_run(queue(), "done")
        for trigger, force in (("manual", False), ("nightly", False), ("follow_up", True), ("settings", True)):
            runs.finish_run(runs.queue_run(REF.slug, trigger, force), "done")
        runs.finish_run(queue(), "done")  # reconnecting on the same branch is not a change either
        self.assertEqual(version(), 1)
        self.assertFalse(repos.get_repo(REF.slug)["needs_rebuild"])
        runs.finish_run(queue(branch="dev"), "done")
        self.assertEqual(version(), 2)
        self.assertFalse(repos.get_repo(REF.slug)["needs_rebuild"])

    def test_adopt_run_records_a_swept_run_as_the_indexed_build(self):
        run_id = queue()
        runs.update_run(run_id, commit_sha="abc", collection="astra_v1__x")
        runs.sweep_interrupted()
        runs.adopt_run(run_id)
        status = runs.latest_run(REF.slug)
        self.assertEqual((status["state"], status["error"]), ("done", runs.RECOVERED_NOTE))
        self.assertEqual(repos.get_repo(REF.slug)["indexed"]["commit_sha"], "abc")
        active = queue()
        runs.adopt_run(active)  # only a failed (swept) run can be adopted
        self.assertEqual(runs.latest_run(REF.slug)["state"], "queued")

    def test_check_results_and_catch_up_selection(self):
        queue()
        repos.mark_checked(REF.slug, "The host rejected the saved token.")
        self.assertEqual(repos.get_repo(REF.slug)["sync"]["source_error"], "The host rejected the saved token.")
        self.assertEqual(repos.due_slugs(24), [])
        with db.transaction() as conn:
            conn.execute("UPDATE repos SET last_checked_at = '2000-01-01T00:00:00+00:00'")
        self.assertEqual(repos.due_slugs(24), [REF.slug])
        repos.mark_checked(REF.slug)
        repo = repos.get_repo(REF.slug)
        self.assertEqual(repo["sync"]["source_error"], "")
        self.assertEqual(repos.due_slugs(24), [])
        repos.request_rebuild(REF.slug)
        self.assertEqual(repos.due_slugs(24), [REF.slug])

    def test_concurrent_queues_start_exactly_one_run(self):
        db.migrate()
        barrier, results = threading.Barrier(8), []

        def attempt():
            barrier.wait()
            results.append(queue())

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(None), 7, results)
        with db.transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0], 1)
        self.assertTrue(repos.get_repo(REF.slug)["sync"]["pending"])

    def test_unknown_run_fields_are_rejected(self):
        run_id = queue()
        with self.assertRaises(ValueError):
            runs.update_run(run_id, **{"state = 'done'; --": 1})
        with self.assertRaises(ValueError):
            runs.finish_run(run_id, "running")


class RuleTests(unittest.TestCase):
    def test_branch_names(self):
        for good in ("main", "dev", "release/2026.10", "feature/ABC-12_x", "v1.0"):
            self.assertEqual(check_branch_name(f" {good} "), good)
        for bad in ("", "-x", "--upload-pack=x", ".hidden", "a/.b", "a..b", "a//b", "a/", "a.", "a.lock",
                    "a b", "a~1", "a^", "a:b", "a\\b", "x" * 201):
            with self.subTest(branch=bad), self.assertRaises(AppError):
                check_branch_name(bad)

    def test_project_ids(self):
        self.assertEqual(check_project_id("proj-1.a_b"), "proj-1.a_b")
        for bad in ("", "a b", "a/b", "x" * 65):
            with self.subTest(project_id=bad), self.assertRaises(AppError):
                check_project_id(bad)


if __name__ == "__main__":
    unittest.main()
