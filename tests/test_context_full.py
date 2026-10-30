import threading
import unittest
from contextlib import ExitStack
from unittest import mock

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from astra_rag import create_app
from astra_rag.services.catalog import CatalogCache, service as catalog_service
from astra_rag.services.context import rerank, service as context_service
from astra_rag.services.context.budget import Budget
from astra_rag.services.errors import AppError
from astra_rag.services.ingestion import pipeline
from astra_rag.services.ingestion.models import Chunk
from astra_rag.services.ingestion.store import QdrantStore, collection_name
from astra_rag.services.ingestion.tokens import count_tokens
from astra_rag.services.registry import repos, runs
from tests.helpers import use_temp_registry
from tests.test_catalog_live import FakeAdapter
from tests.test_context import FILES
from tests.test_ingestion import FakeEmbedder
from tests.test_routes import SLUG, fake_adapter

REQUEST = dict(doc_type="BRD", stage="design", tags=["payments"], text="refund limit for cash on delivery")
DOCS = {
    "a": ("Cash on delivery limit is 10,000 INR.", "emails/a.md", "email", "2026-01-05"),
    "b": ("Cash on delivery limit was revised to 7,500 INR.", "meeting-notes/b.md", "meeting-note", "2026-03-02"),
    "c": ("The refund window is 30 days for card payments.", "requirements/c.md", "requirement", None),
}


class FakeReranker:
    """Longest text first: an order the search itself would not give."""

    def score(self, query, texts):
        return [float(len(t)) for t in texts]


class ContextTestBase(unittest.TestCase):
    def setUp(self):
        use_temp_registry(self)
        catalog_service._cache = CatalogCache()
        self.adapter = FakeAdapter(FILES)
        runs.register_and_queue(fake_adapter().ref, "https://github.com/acme/golden", "main", "ref")
        repos.bind_project("proj-1", SLUG)
        self.embedder = FakeEmbedder()
        self.store = QdrantStore(QdrantClient(":memory:"))
        self.store.create(collection_name(SLUG), self.embedder.dense_dim)
        chunks = [Chunk(key, text, text, {"text": text, "path": path, "heading_path": ["Notes"], "doc_type": kind,
                                          "doc_date": date, "source_url": f"https://host/{path}", "file_type": "md",
                                          "folder_top": path.split("/")[0]})
                  for key, (text, path, kind, date) in DOCS.items()]
        dense, sparse = self.embedder.embed_passages([c.embed_text for c in chunks])
        self.store.upsert(collection_name(SLUG), chunks, dense, sparse)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(pipeline, "QdrantStore", return_value=self.store))
        stack.enter_context(mock.patch.object(pipeline, "get_embedder", return_value=self.embedder))
        stack.enter_context(mock.patch.object(rerank, "get_reranker", return_value=FakeReranker()))
        stack.enter_context(mock.patch("astra_rag.services.catalog.service.adapter_for",
                                       mock.Mock(return_value=self.adapter)))
        stack.enter_context(mock.patch("astra_rag.services.catalog.service.token_store.get_token",
                                       mock.Mock(return_value="tok")))
        self.client = TestClient(create_app())

    def post(self, **body):
        return self.client.post("/api/context", json={"project_id": "proj-1", **{**REQUEST, **body}})


class ContextResponseTests(ContextTestBase):
    def test_response_has_rules_template_knowledge_and_status(self):
        data = self.post().json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["request"], {"doc_type": "BRD", "stage": "design", "tags": ["payments"]})
        self.assertEqual(data["snapshot"], {"rules_commit": "c1", "index_commit": None})
        self.assertEqual([r["section"] for r in data["rules"]], ["Data handling", "PCI", "Sign-off", "Design checks"])
        self.assertEqual(data["template"]["text"], FILES["templates/brd/payments-design.md"])
        self.assertFalse(data["template"]["truncated"])
        self.assertEqual(data["status"], {"rules": "ok", "knowledge": "ok", "rerank": "ok"})
        self.assertEqual(data["budget"]["truncated"], [])
        knowledge = data["knowledge"]
        self.assertEqual((knowledge["total_count"], knowledge["truncated"]), (3, False))
        item = knowledge["items"][0]
        for key in ("text", "file", "heading_path", "doc_type", "doc_date", "source_url"):
            self.assertIn(key, item)

    def test_every_matching_source_is_returned_with_its_date_and_type_and_none_is_preferred(self):
        items = self.post().json()["knowledge"]["items"]
        by_file = {i["file"]: i for i in items}
        self.assertEqual((by_file["emails/a.md"]["doc_date"], by_file["emails/a.md"]["doc_type"]), ("2026-01-05", "email"))
        self.assertEqual(by_file["meeting-notes/b.md"]["doc_date"], "2026-03-02")
        self.assertIn("10,000", by_file["emails/a.md"]["text"])  # the older, conflicting source is not dropped
        self.assertIn("7,500", by_file["meeting-notes/b.md"]["text"])

    def test_one_search_per_request_whatever_the_template_headings(self):
        with mock.patch.object(pipeline, "search", wraps=pipeline.search) as search:
            self.post()
            self.assertEqual(search.call_count, 1)
            self.assertEqual(search.call_args.args[:2], (SLUG, REQUEST["text"]))

    def test_token_is_never_returned(self):
        self.assertNotIn('"tok"', self.post().text)

    def test_blank_text_and_bad_budget_and_unknown_inputs_are_rejected(self):
        self.assertEqual(self.post(text="   ").status_code, 422)
        self.assertEqual(self.post(budget=10).status_code, 422)
        self.assertEqual(self.post(doc_type="memo").status_code, 422)
        self.assertEqual(self.client.post("/api/context", json={"project_id": "x", **REQUEST}).status_code, 404)
        self.assertEqual(self.client.post("/api/context", json={"project_id": "proj-1", "doc_type": "BRD"}).status_code, 422)


class RerankTests(ContextTestBase):
    def test_rerank_orders_the_items_and_scores_them(self):
        items = self.post().json()["knowledge"]["items"]
        lengths = [len(i["text"]) for i in items]
        self.assertEqual(lengths, sorted(lengths, reverse=True))
        self.assertTrue(all("rerank_score" in i for i in items))

    def test_weak_matches_below_the_floor_are_dropped_and_counted(self):
        class Scores:  # one relevant chunk, two unrelated
            def score(self, query, texts):
                return [3.0 if "7,500" in t else -9.0 for t in texts]

        data = context_service.get_context("proj-1", reranker=Scores(), **REQUEST)["knowledge"]
        self.assertEqual([i["file"] for i in data["items"]], ["meeting-notes/b.md"])
        self.assertEqual((data["total_count"], data["below_threshold"]), (1, 2))

    def test_nothing_relevant_gives_no_items_and_a_status(self):
        class Unrelated:
            def score(self, query, texts):
                return [-9.0] * len(texts)

        data = context_service.get_context("proj-1", reranker=Unrelated(), **REQUEST)
        self.assertEqual(data["knowledge"]["items"], [])
        self.assertEqual(data["status"]["knowledge"], "no_relevant_match")
        self.assertTrue(data["rules"] and data["template"])  # rules and template are unaffected

    def test_a_skipped_rerank_keeps_every_hit(self):
        class Broken:
            def score(self, query, texts):
                raise RuntimeError("x")

        data = context_service.get_context("proj-1", reranker=Broken(), **REQUEST)
        self.assertEqual((len(data["knowledge"]["items"]), data["knowledge"]["below_threshold"]), (3, 0))

    def test_a_slow_reranker_is_skipped_and_the_search_order_is_kept(self):
        release = threading.Event()
        self.addCleanup(release.set)

        class Slow:
            def score(self, query, texts):
                release.wait(2)
                return [0.0] * len(texts)

        with mock.patch.object(rerank, "RERANK_TIMEOUT_SECONDS", 0.05):
            data = context_service.get_context("proj-1", reranker=Slow(), **REQUEST)
        self.assertEqual(data["status"]["rerank"], "skipped: timeout")
        self.assertEqual(len(data["knowledge"]["items"]), 3)
        self.assertTrue(all("rerank_score" not in i for i in data["knowledge"]["items"]))
        release.set()
        rerank._pool.submit(lambda: None).result(5)  # let the abandoned call finish before the next test

    def test_a_failing_reranker_is_skipped_and_never_leaks_its_message(self):
        class Broken:
            def score(self, query, texts):
                raise RuntimeError("secret detail")

        data = context_service.get_context("proj-1", reranker=Broken(), **REQUEST)
        self.assertEqual(data["status"]["rerank"], "skipped: RuntimeError")
        self.assertNotIn("secret", str(data))
        self.assertEqual(len(data["knowledge"]["items"]), 3)


class DegradedModeTests(ContextTestBase):
    def test_qdrant_down_still_returns_rules_and_template(self):
        class Down(QdrantStore):
            def ping(self):
                raise AppError("Could not reach Qdrant.", 503)

        with mock.patch.object(pipeline, "QdrantStore", return_value=Down(QdrantClient(":memory:"))):
            data = self.post().json()
        self.assertEqual(data["status"]["knowledge"], "unavailable: Could not reach Qdrant.")
        self.assertEqual(data["status"]["rerank"], "not_run")
        self.assertEqual(data["knowledge"], {"items": [], "total_count": 0, "truncated": False, "below_threshold": 0})
        self.assertEqual(len(data["rules"]), 4)
        self.assertTrue(data["template"]["text"])

    def test_a_repo_with_no_index_says_so(self):
        class NoIndex(QdrantStore):  # a real server answers 404 for a missing collection; the store maps it to this
            def search(self, *args, **kwargs):
                raise AppError("No index exists for this repository yet.", 404)

        with mock.patch.object(pipeline, "QdrantStore", return_value=NoIndex(QdrantClient(":memory:"))):
            data = self.post().json()
        self.assertEqual(data["status"]["knowledge"], "no_index")
        self.assertEqual(len(data["rules"]), 4)

    def test_no_matching_evidence_is_empty_not_an_error(self):
        self.store.client.delete_collection(collection_name(SLUG))
        self.store.create(collection_name(SLUG), self.embedder.dense_dim)
        data = self.post().json()
        self.assertEqual(data["status"]["knowledge"], "empty")

    def test_host_down_serves_the_cached_catalog_marked_stale(self):
        self.post()
        self.adapter.fail = AppError("Could not reach the host.", 502)
        data = self.post().json()
        self.assertEqual(data["status"]["rules"], "stale")
        self.assertTrue(data["stale"])
        self.assertEqual(data["status"]["knowledge"], "ok")


class BudgetTests(ContextTestBase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(context_service, "CONTEXT_BUDGET_RANGE", (1, 100_000))
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, budget=None):
        return context_service.get_context("proj-1", budget=budget, **REQUEST)

    def test_order_is_always_rules_then_template_then_scope_rules_then_knowledge(self):
        full = self.get()
        always = sum(count_tokens(r["text"]) for r in full["rules"] if r["matched_on"] == "always")
        template = count_tokens(full["template"]["text"])
        data = self.get(always + template)
        self.assertEqual([r["matched_on"] for r in data["rules"]], ["always"])
        self.assertEqual(data["template"]["text"], full["template"]["text"])
        self.assertEqual(data["budget"]["truncated"], ["scope_rules", "knowledge"])
        self.assertTrue(data["knowledge"]["truncated"])
        self.assertEqual(data["knowledge"]["items"], [])
        self.assertEqual(data["budget"]["used"], always + template)
        self.assertIn("budget_truncated", [w["code"] for w in data["warnings"]])

    def test_a_tiny_budget_flags_every_section_and_never_exceeds_the_limit(self):
        data = self.get(1)
        self.assertEqual(data["budget"]["truncated"], ["always_rules", "template", "scope_rules", "knowledge"])
        self.assertEqual(data["rules"], [])
        self.assertEqual((data["template"]["text"], data["template"]["truncated"]), ("", True))
        self.assertLessEqual(data["budget"]["used"], 1)

    def test_a_template_over_the_budget_keeps_whole_leading_lines(self):
        full = self.get()
        always = sum(count_tokens(r["text"]) for r in full["rules"] if r["matched_on"] == "always")
        first_line = FILES["templates/brd/payments-design.md"].splitlines(keepends=True)[0]
        data = self.get(always + count_tokens(first_line))
        self.assertEqual(data["template"]["text"], first_line)
        self.assertTrue(data["template"]["truncated"])

    def test_enough_budget_truncates_nothing(self):
        self.assertEqual(self.get(100_000)["budget"]["truncated"], [])


class BudgetUnitTests(unittest.TestCase):
    def test_items_stop_at_the_first_one_that_does_not_fit(self):
        budget = Budget(5)
        kept = budget.take_items(["a b", "c d e f g", "h"], "rules", str)  # 2, 5, 1 tokens
        self.assertEqual(kept, ["a b"])  # "h" fits but order is priority, so it is not taken
        self.assertEqual((budget.used, budget.truncated), (2, ["rules"]))

    def test_a_section_is_flagged_once(self):
        budget = Budget(0)
        budget.take_items(["a"], "knowledge", str)
        budget.take_items(["b"], "knowledge", str)
        self.assertEqual(budget.truncated, ["knowledge"])


if __name__ == "__main__":
    unittest.main()
