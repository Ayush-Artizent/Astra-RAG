import unittest
from unittest import mock

from fastapi.testclient import TestClient

from astra_rag import create_app
from astra_rag.services.cloner import CloneResult
from astra_rag.services.errors import AppError
from astra_rag.services.ingestion import pipeline

FULL_ROOT = [
    {"name": "policies.md", "type": "file"}, {"name": "nomenclature.md", "type": "file"},
    {"name": "project-data", "type": "dir"}, {"name": "templates", "type": "dir"},
]
CLONE = CloneResult("/tmp/x", "abc123", "main")


def fake_adapter(entries):
    adapter = mock.MagicMock()
    adapter.list_dir.return_value = entries
    return adapter


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.body = {"url": "https://github.com/acme/golden", "token": "t"}

    def test_clone_queues_ingestion_with_commit_and_status_is_readable(self):
        with mock.patch("astra_rag.routes.adapter_for", return_value=fake_adapter(FULL_ROOT)), \
                mock.patch("astra_rag.routes.cloner.clone_repo", return_value=CLONE), \
                mock.patch("astra_rag.routes.token_store.save") as save, \
                mock.patch("astra_rag.routes.pipeline.run_ingestion") as run:
            res = self.client.post("/api/validate-and-clone", json=self.body)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["commit_sha"], "abc123")
        self.assertEqual(data["ingestion"], {"slug": "github.com__acme__golden", "state": "queued"})
        run.assert_called_once()
        save.assert_called_once()
        self.assertEqual(save.call_args.args[2], "t")
        self.assertTrue(data["token_saved"])
        context = run.call_args.args[0]
        self.assertEqual((context.owner, context.name, context.branch, context.commit_sha),
                         ("acme", "golden", "main", "abc123"))

        status = self.client.get("/api/ingestion-status/github.com__acme__golden").json()
        self.assertEqual(status["state"], "queued")
        self.assertEqual(status["commit_sha"], "abc123")

    def test_blank_token_reuses_saved_one_and_does_not_rewrite_it(self):
        with mock.patch("astra_rag.routes.token_store.get_token", return_value="saved-secret"), \
                mock.patch("astra_rag.routes.adapter_for", return_value=fake_adapter(FULL_ROOT)) as adapter_for, \
                mock.patch("astra_rag.routes.cloner.clone_repo", return_value=CLONE) as clone_repo, \
                mock.patch("astra_rag.routes.token_store.save") as save, \
                mock.patch("astra_rag.routes.pipeline.run_ingestion"):
            res = self.client.post("/api/validate-and-clone", json={**self.body, "token": ""})
        data = res.json()
        self.assertTrue(data["ok"] and data["token_reused"] and not data["token_saved"])
        self.assertEqual(adapter_for.call_args.args[1].secret(), "saved-secret")
        clone_repo.assert_called_once_with(adapter_for.return_value)
        save.assert_not_called()
        self.assertNotIn("saved-secret", res.text)

    def test_no_typed_and_no_saved_token_is_rejected(self):
        with mock.patch("astra_rag.routes.token_store.get_token", return_value=None):
            res = self.client.post("/api/validate-and-clone", json={**self.body, "token": " "})
        self.assertEqual(res.status_code, 400)

    def test_token_is_saved_once_the_host_accepts_it_even_if_the_clone_fails(self):
        with mock.patch("astra_rag.routes.adapter_for", return_value=fake_adapter(FULL_ROOT)), \
                mock.patch("astra_rag.routes.cloner.clone_repo", side_effect=AppError("boom", 502)), \
                mock.patch("astra_rag.routes.token_store.save") as save:
            res = self.client.post("/api/validate-and-clone", json=self.body)
        self.assertEqual(res.status_code, 502)
        save.assert_called_once()

    def test_rejected_token_is_not_saved(self):
        adapter = fake_adapter(FULL_ROOT)
        adapter.list_dir.side_effect = AppError("rejected the token", 401)
        with mock.patch("astra_rag.routes.adapter_for", return_value=adapter), \
                mock.patch("astra_rag.routes.token_store.save") as save:
            res = self.client.post("/api/validate-and-clone", json=self.body)
        self.assertEqual(res.status_code, 401)
        save.assert_not_called()

    def test_missing_structure_saves_the_token_but_does_not_start_ingestion(self):
        with mock.patch("astra_rag.routes.adapter_for", return_value=fake_adapter(FULL_ROOT[:2])), \
                mock.patch("astra_rag.routes.token_store.save") as save, \
                mock.patch("astra_rag.routes.pipeline.mark_queued") as queued:
            res = self.client.post("/api/validate-and-clone", json=self.body)
        self.assertEqual(res.status_code, 422)
        self.assertTrue(res.json()["token_saved"])
        save.assert_called_once()
        queued.assert_not_called()

    def test_status_404_when_unknown(self):
        res = self.client.get("/api/ingestion-status/github.com__nobody__nothing")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.json()["ok"])

    def test_search_requires_query(self):
        with mock.patch.object(pipeline, "QdrantStore"):
            res = self.client.post("/api/search", json={"slug": "github.com__a__b", "query": " "})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
