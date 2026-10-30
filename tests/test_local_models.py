import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from astra_rag import create_app
from astra_rag.services import local_models
from astra_rag.services.context import rerank
from astra_rag.services.ingestion import embedder


class LocalModelsBase(unittest.TestCase):
    """Real prefetch logic with the model loading faked; state is reset around every test."""

    def setUp(self):
        fresh = {n: {"state": "pending", "error": ""} for n in local_models.COMPONENTS}
        for patcher in (
            mock.patch.object(local_models, "MODELS_PREFETCH", True),
            mock.patch.object(local_models, "_state", fresh),
            mock.patch.object(local_models, "_running", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.loaded = []
        self.fail = {}
        patcher = mock.patch.object(local_models, "_load", side_effect=self._load)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _load(self, name):
        self.loaded.append(name)
        if name in self.fail:
            raise self.fail[name]

    def finish(self, names=("embedder", "reranker")):
        local_models.wait_ready(names, timeout=5)


class PrefetchTests(LocalModelsBase):
    def test_nothing_is_ready_until_the_prefetch_has_run(self):
        with self.assertRaises(local_models.ModelsNotReady) as caught:
            local_models.require_ready("embedder")
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse(local_models.status()["ready"])

    def test_prefetch_prepares_every_model_in_order_and_marks_them_ready(self):
        local_models.start_prefetch()
        self.finish()
        self.assertEqual(self.loaded, ["embedder", "reranker"])
        local_models.require_ready("embedder")
        local_models.require_ready("reranker")
        status = local_models.status()
        self.assertTrue(status["ready"])
        self.assertEqual([c["name"] for c in status["components"]], ["embedder", "reranker"])
        self.assertEqual(status["components"][0]["models"], local_models.COMPONENTS["embedder"])

    def test_a_ready_set_is_not_prepared_twice(self):
        local_models.start_prefetch()
        self.finish()
        local_models.start_prefetch()
        local_models.wait_ready(("embedder", "reranker"))
        self.assertEqual(self.loaded, ["embedder", "reranker"])

    def test_one_failing_model_does_not_stop_the_others_and_names_only_the_error_type(self):
        self.fail["reranker"] = ConnectionError("https://secret.example/host-reply")
        local_models.start_prefetch()
        with self.assertRaises(local_models.ModelsNotReady) as caught:
            self.finish()
        local_models.require_ready("embedder")  # still usable
        self.assertIn("ConnectionError", caught.exception.message)
        self.assertNotIn("secret.example", caught.exception.message)
        self.assertEqual(local_models.status()["components"][1]["error"], "ConnectionError")

    def test_a_failed_model_is_tried_again_by_the_next_wait(self):
        self.fail["embedder"] = OSError("offline")
        local_models.start_prefetch()
        with self.assertRaises(local_models.ModelsNotReady):
            self.finish(("embedder",))
        del self.fail["embedder"]
        local_models.wait_ready(("embedder",), timeout=5)
        local_models.require_ready("embedder")

    def test_wait_ready_blocks_until_the_download_finishes(self):
        gate = threading.Event()
        real = self._load

        def slow(name):
            gate.wait(5)
            real(name)

        with mock.patch.object(local_models, "_load", side_effect=slow):
            local_models.start_prefetch()
            done = threading.Event()
            waiter = threading.Thread(target=lambda: (local_models.wait_ready(("embedder",), timeout=5), done.set()))
            waiter.start()
            self.assertFalse(done.wait(0.3))  # still downloading
            gate.set()
            self.assertTrue(done.wait(5))
            waiter.join(5)
            self.finish()  # let the reranker step end before the patches are undone

    def test_with_prefetch_off_nothing_waits_or_fails(self):
        with mock.patch.object(local_models, "MODELS_PREFETCH", False):
            local_models.start_prefetch()
            local_models.wait_ready()
            local_models.require_ready("embedder")
        self.assertEqual(self.loaded, [])


class GateTests(LocalModelsBase):
    """The real get_embedder / get_reranker refuse to download inside a request."""

    def test_get_embedder_and_get_reranker_fail_fast_until_ready(self):
        with self.assertRaises(local_models.ModelsNotReady):
            embedder.get_embedder()
        with self.assertRaises(local_models.ModelsNotReady):
            rerank.get_reranker()

    def test_rerank_is_skipped_with_a_reason_while_the_reranker_is_not_ready(self):
        items = [{"text": "a"}, {"text": "b"}]
        out, status = rerank.rerank("q", items)
        self.assertEqual((out, status), (items, "skipped: models_not_ready"))

    def test_the_models_endpoint_reports_state_without_failing(self):
        client = TestClient(create_app())
        data = client.get("/api/health/models").json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["ready"])
        self.assertEqual([c["state"] for c in data["components"]], ["pending", "pending"])
        local_models.start_prefetch()
        self.finish()
        self.assertTrue(client.get("/api/health/models").json()["ready"])


if __name__ == "__main__":
    unittest.main()
