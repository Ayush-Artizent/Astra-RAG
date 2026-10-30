import hashlib
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from qdrant_client import QdrantClient

from astra_rag.config import CHUNK_MAX_TOKENS
from astra_rag.services.errors import AppError
from astra_rag.services.ingestion import pipeline
from astra_rag.services.ingestion.chunker import chunk_document
from astra_rag.services.ingestion.csv_chunker import chunk_csv
from astra_rag.services.ingestion.loader import load_documents
from astra_rag.services.ingestion.md_chunker import chunk_markdown
from astra_rag.services.ingestion.models import Document, RepoContext
from astra_rag.services.ingestion.store import QdrantStore, collection_name, point_id, version_name
from astra_rag.services.ingestion.tokens import count_tokens
from astra_rag.services.registry import repos, runs
from astra_rag.services.sources.registry import parse_repo_url
from tests.helpers import use_temp_registry

REPO = RepoContext(parse_repo_url("https://github.com/acme/golden"), "main", "abc123def456")
SLUG = "github.com__acme__golden"

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "repo"


class FakeEmbedder:
    """Hash-based vectors: no model download, deterministic, shares words -> similar."""
    dense_dim = 16
    model_name = "fake-embedder"

    def _words(self, text):
        return re.findall(r"\w+", text.lower())

    def _dense(self, text):
        v = [0.0] * self.dense_dim
        for w in self._words(text):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dense_dim] += 1.0
        return v

    def _sparse(self, text):
        weights = {}
        for w in self._words(text):
            idx = int(hashlib.md5(w.encode()).hexdigest(), 16) % 100_000
            weights[idx] = weights.get(idx, 0.0) + 1.0
        return list(weights), list(weights.values())

    def embed_passages(self, texts):
        return [self._dense(t) for t in texts], [self._sparse(t) for t in texts]

    def embed_query(self, text):
        return self._dense(text), self._sparse(text)


def make_docx(path: Path, paragraphs: list[tuple[str, str]]) -> None:
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'
        for style, text in paragraphs
    )
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}</w:body></w:document>")
    content_types = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)


class LoaderTests(unittest.TestCase):
    def test_loads_supported_and_reports_skipped(self):
        docs, skipped = load_documents(FIXTURE_REPO)
        self.assertEqual(sorted(d.path for d in docs), [
            "project-data/finance/budget.csv", "project-data/hr/2024/onboarding.txt",
            "project-data/hr/leave-policy.md"])
        reasons = {s.path: s.reason for s in skipped}
        self.assertIn("unsupported", reasons["project-data/finance/logo.png"])
        self.assertEqual(reasons["project-data/finance/empty.csv"], "empty file")

    def test_missing_project_data_returns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_documents(Path(tmp)), ([], []))

    def test_docx_is_converted_to_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "project-data" / "specs"
            folder.mkdir(parents=True)
            make_docx(folder / "spec.docx", [("Heading1", "Payment Spec"), ("Normal", "Refunds take five days.")])
            docs, skipped = load_documents(Path(tmp))
        self.assertEqual(skipped, [])
        self.assertEqual(docs[0].file_type, "docx")
        self.assertIn("Payment Spec", docs[0].text)
        self.assertIn("Refunds take five days.", docs[0].text)


def symlink_or_skip(test: unittest.TestCase, link: Path, target: Path) -> None:
    """Symlink if allowed; for folders on Windows fall back to a junction (needs no privileges)."""
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError):
        pass
    if target.is_dir() and sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return
    test.skipTest("symlinks cannot be created on this system")


class LoaderSymlinkTests(unittest.TestCase):
    """A hostile repo must not be able to pull files from outside the clone into the index."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.outside = base / "outside"
        self.outside.mkdir()
        (self.outside / "secret.md").write_text("# Secret\nASTRA_REPO_TOKEN=ghp_leak", encoding="utf-8")
        self.repo = base / "repo"
        self.data = self.repo / "project-data"
        self.data.mkdir(parents=True)
        (self.data / "real.md").write_text("# Real\nKept.", encoding="utf-8")

    def test_file_link_is_skipped_and_reported(self):
        symlink_or_skip(self, self.data / "leak.md", self.outside / "secret.md")
        docs, skipped = load_documents(self.repo)
        self.assertEqual([d.path for d in docs], ["project-data/real.md"])
        self.assertIn("symbolic link", {s.path: s.reason for s in skipped}["project-data/leak.md"])

    def test_folder_link_is_not_followed(self):
        symlink_or_skip(self, self.data / "linked", self.outside)
        docs, skipped = load_documents(self.repo)
        self.assertEqual([d.path for d in docs], ["project-data/real.md"])
        self.assertEqual([s.path for s in skipped], ["project-data/linked"])

    def test_project_data_itself_linked_outside_loads_nothing(self):
        repo = self.repo.parent / "repo2"
        repo.mkdir()
        symlink_or_skip(self, repo / "project-data", self.outside)
        docs, skipped = load_documents(repo)
        self.assertEqual(docs, [])
        self.assertEqual([s.path for s in skipped], ["project-data"])


class MarkdownChunkerTests(unittest.TestCase):
    def test_headings_become_breadcrumbs_and_lines_are_tracked(self):
        text = "# Title\n\nIntro.\n\n## A\n\nalpha " + "word " * 400 + "\n\n## B\n\nbeta\n"
        chunks = chunk_markdown(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.start and c.end and c.start <= c.end for c in chunks))
        self.assertIn(("Title", "A"), [c.heading_path for c in chunks])
        self.assertIn(("Title", "B"), [c.heading_path for c in chunks])

    def test_all_chunks_under_cap_even_for_huge_paragraphs(self):
        text = "# T\n\n" + ("lorem ipsum dolor sit amet " * 3000) + "\n"
        for c in chunk_markdown(text):
            self.assertLessEqual(count_tokens(c.text), CHUNK_MAX_TOKENS)

    def test_code_fence_and_table_stay_whole(self):
        text = "# T\n\n```python\nx = 1\n\ny = 2\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        joined = "\n\n".join(c.text for c in chunk_markdown(text))
        self.assertIn("```python\nx = 1\n\ny = 2\n```", joined)
        self.assertIn("| a | b |\n|---|---|\n| 1 | 2 |", joined)

    def test_oversize_table_repeats_header(self):
        rows = "\n".join(f"| row{i} | " + "value " * 20 + "|" for i in range(120))
        chunks = chunk_markdown("| h1 | h2 |\n|----|----|\n" + rows)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertTrue(c.text.startswith("| h1 | h2 |\n|----|----|"))
            self.assertLessEqual(count_tokens(c.text), CHUNK_MAX_TOKENS)

    def test_each_section_is_its_own_chunk_with_its_own_path(self):
        text = "# Epic\n\nintro\n\n## Scope\n\n- in\n\n## Not in scope\n\n- out\n"
        chunks = chunk_markdown(text)
        self.assertEqual([c.heading_path for c in chunks],
                         [("Epic",), ("Epic", "Scope"), ("Epic", "Not in scope")])
        self.assertNotIn("out", chunks[1].text)
        self.assertNotIn("- in", chunks[2].text)

    def test_heading_without_body_makes_no_chunk_and_text_before_first_heading_is_kept(self):
        chunks = chunk_markdown("From: a\nSubject: s\n\nbody\n\n# T\n\n## Child\n\nx\n")
        self.assertEqual([c.heading_path for c in chunks], [(), ("T", "Child")])
        self.assertIn("Subject: s", chunks[0].text)

    def test_oversize_section_splits_but_every_piece_keeps_the_section_path(self):
        text = "# T\n\n## Big\n\n" + "\n\n".join("para " * 120 for _ in range(6)) + "\n\n## Small\n\nx\n"
        chunks = chunk_markdown(text)
        self.assertGreater(len([c for c in chunks if c.heading_path == ("T", "Big")]), 1)
        self.assertEqual([c for c in chunks if c.heading_path == ("T", "Small")][0].text, "## Small\n\nx")

    def test_heading_is_never_cut_off_from_its_body(self):
        chunks = chunk_markdown("# T\n\n" + "para " * 330 + "\n\n## Next\n\n" + "word " * 500 + "\n")
        for c in chunks:
            self.assertFalse(c.text.rstrip().splitlines()[-1].startswith("#"))

    def test_hash_inside_code_fence_is_not_a_heading(self):
        chunks = chunk_markdown("# T\n\n```bash\n# just a comment\n```\n")
        self.assertEqual(chunks[0].heading_path, ("T",))


class CsvChunkerTests(unittest.TestCase):
    def test_summary_plus_one_chunk_per_row_keyed_by_id_column(self):
        chunks, warnings = chunk_csv("name,id\nA,X-1\nB,X-2\n", "t.csv")
        self.assertEqual(warnings, [])
        self.assertEqual([c.kind for c in chunks], ["csv_summary", "csv_row", "csv_row"])
        self.assertIn("Rows: 2", chunks[0].text)
        self.assertEqual([c.extra["row_key"] for c in chunks[1:]], ["X-1", "X-2"])
        self.assertEqual([(c.extra["row_start"], c.extra["row_end"]) for c in chunks[1:]], [(1, 1), (2, 2)])
        self.assertIn("name: B", chunks[2].text)
        self.assertNotIn("name: A", chunks[2].text)

    def test_key_defaults_to_first_column(self):
        chunks, _ = chunk_csv("title,x\nfoo,1\n", "t.csv")
        self.assertEqual(chunks[1].extra["row_key"], "foo")

    def test_semicolon_delimiter_and_blank_cells(self):
        chunks, _ = chunk_csv("a;b\n1;\n2;two\n", "t.csv")
        self.assertIn("a: 1", chunks[1].text)
        self.assertNotIn("b:", chunks[1].text)
        self.assertIn("b: two", chunks[2].text)

    def test_pathological_row_still_fits(self):
        chunks, _ = chunk_csv("a\n" + "word " * 5000 + "\n", "t.csv")
        for c in chunks:
            self.assertLessEqual(count_tokens(c.text), CHUNK_MAX_TOKENS)


class ChunkerMetadataTests(unittest.TestCase):
    def setUp(self):
        docs, _ = load_documents(FIXTURE_REPO)
        self.docs = {d.path: d for d in docs}

    def test_markdown_metadata_is_complete_and_traceable(self):
        chunks, _ = chunk_document(self.docs["project-data/hr/leave-policy.md"], REPO)
        p = chunks[0].payload
        self.assertEqual(p["repo"], "acme/golden")
        self.assertEqual(p["commit_sha"], "abc123def456")
        self.assertEqual(p["folder_parts"], ["project-data", "hr"])
        self.assertEqual(p["folder_top"], "hr")
        self.assertEqual(p["chunk_count"], len(chunks))
        self.assertEqual(p["text"], chunks[0].text)
        self.assertRegex(p["source_url"], r"^https://github\.com/acme/golden/blob/abc123def456/project-data/hr/leave-policy\.md#L\d+-L\d+$")
        self.assertTrue(chunks[0].embed_text.startswith("Leave Policy"))
        self.assertNotIn("Leave Policy >", chunks[0].text)

    def test_csv_metadata_has_rows_not_lines(self):
        chunks, _ = chunk_document(self.docs["project-data/finance/budget.csv"], REPO)
        rows = [c for c in chunks if c.payload["chunk_kind"] == "csv_row"][0].payload
        self.assertEqual((rows["row_start"], rows["row_end"]), (1, 1))
        self.assertEqual(rows["row_key"], "B-001")
        self.assertIsNone(rows["line_start"])
        self.assertTrue(rows["source_url"].endswith("budget.csv"))

    def test_ids_are_deterministic_and_unique(self):
        doc = self.docs["project-data/hr/leave-policy.md"]
        a, _ = chunk_document(doc, REPO)
        b, _ = chunk_document(doc, REPO)
        self.assertEqual([c.chunk_id for c in a], [c.chunk_id for c in b])
        self.assertEqual(len({c.chunk_id for c in a}), len(a))
        self.assertEqual(point_id(a[0].chunk_id), point_id(b[0].chunk_id))

    def test_file_directly_in_project_data_has_empty_folder_top(self):
        doc = Document("project-data/readme.md", "md", "h", "# R\n\nhello\n")
        chunks, _ = chunk_document(doc, REPO)
        self.assertEqual(chunks[0].payload["folder_top"], "")


class DocMetadataTests(unittest.TestCase):
    EMAIL = "From: Payments Lead\nTo: Squad\nDate: 2026-10-02\nSubject: Failover\n\nPrimary: Razorpay.\n"
    MEETING = "# Sync\n**Date:** 2026-09-05 \u00b7 **Attendees:** PO, QA\n- Open: limit? **Finance to decide.**\n- Done: x\n"

    def _chunks(self, path, text):
        chunks, _ = chunk_document(Document(path, "md", "h", text), REPO)
        return chunks

    def test_email_header_becomes_fields_and_body_line_is_not_a_field(self):
        p = self._chunks("project-data/emails/2026-10-02-x.md", self.EMAIL)[0].payload
        self.assertEqual(p["doc_type"], "email")
        self.assertEqual(p["doc_date"], "2026-10-02")
        self.assertEqual(p["doc_meta"], {"from": "Payments Lead", "to": "Squad", "date": "2026-10-02",
                                         "subject": "Failover"})
        self.assertEqual(p["title"], "Failover")

    def test_meeting_header_and_open_items(self):
        chunk = self._chunks("project-data/meeting-notes/n.md", self.MEETING)[0]
        p = chunk.payload
        self.assertEqual((p["doc_type"], p["doc_date"]), ("meeting-note", "2026-09-05"))
        self.assertEqual(p["doc_meta"]["attendees"], "PO, QA")
        self.assertTrue(p["has_open_item"])
        self.assertEqual(len(p["open_items"]), 1)
        self.assertIn("meeting-note | 2026-09-05", chunk.embed_text)

    def test_italic_owner_line_gives_owner_and_date(self):
        text = "# E\n_Owner: PO \u00b7 2026-08-28_\n\n## Why\n\nbecause\n"
        p = self._chunks("project-data/requirements/e.md", text)[0].payload
        self.assertEqual((p["doc_type"], p["doc_date"], p["doc_meta"]), ("requirement", "2026-08-28", {"owner": "PO"}))

    def test_date_falls_back_to_filename_and_unknown_folder_keeps_its_name(self):
        p = self._chunks("project-data/misc/2026-01-02-note.md", "# N\n\nhi\n")[0].payload
        self.assertEqual((p["doc_type"], p["doc_date"]), ("misc", "2026-01-02"))
        p = self._chunks("project-data/readme.md", "# R\n\nhi\n")[0].payload
        self.assertEqual((p["doc_type"], p["doc_date"], p["has_open_item"]), ("document", None, False))

    def test_plain_prose_with_colon_is_not_metadata(self):
        p = self._chunks("project-data/hr/x.md", "Note: this is fine\n\nbody\n")[0].payload
        self.assertEqual(p["doc_meta"], {})


class HorizontalRuleTests(unittest.TestCase):
    def test_rules_are_omitted_and_do_not_split_a_chunk(self):
        text = "# T\n\n## One\n\nfirst para\n\n---\n\nsecond para\n\n***\n\n___\n\n## Two\n\nbeta\n\n---\n"
        chunks = chunk_markdown(text)
        self.assertEqual([c.heading_path for c in chunks], [("T", "One"), ("T", "Two")])
        self.assertEqual(chunks[0].text, "## One\n\nfirst para\n\nsecond para")
        self.assertEqual(chunks[1].text, "## Two\n\nbeta")

    def test_line_numbers_still_count_the_omitted_rule(self):
        chunks = chunk_markdown("# T\n\n## One\n\nalpha\n\n---\n\nbeta\n")
        self.assertEqual((chunks[0].start, chunks[0].end), (3, 9))

    def test_section_with_only_a_rule_makes_no_chunk(self):
        chunks = chunk_markdown("# T\n\n## Empty\n\n---\n\n## Full\n\nx\n")
        self.assertEqual([c.heading_path for c in chunks], [("T", "Full")])

    def test_table_separator_code_fence_and_setext_underline_are_untouched(self):
        self.assertIn("|---|---|", chunk_markdown("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")[0].text)
        self.assertIn("```md\n---\n```", chunk_markdown("# T\n\n```md\n---\n```\n")[0].text)
        self.assertIn("Title\n---", chunk_markdown("Title\n---\n\nbody\n")[0].text)

    def test_rule_directly_after_a_table_is_omitted_and_the_table_stays_whole(self):
        chunks = chunk_markdown("# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n---\nafter\n")
        self.assertEqual(chunks[0].text, "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nafter")

    def test_rule_is_not_in_text_or_embedded_text(self):
        doc = Document("project-data/x/n.md", "md", "h", "# T\n\n## One\n\na\n\n---\n\nb\n")
        chunks, _ = chunk_document(doc, REPO)
        self.assertNotIn("---", chunks[0].text)
        self.assertNotIn("---", chunks[0].embed_text)


class StoreVersionTests(unittest.TestCase):
    def setUp(self):
        self.store = QdrantStore(QdrantClient(":memory:"))

    def test_version_names_belong_to_one_repo_only(self):
        from astra_rag.services.ingestion.store import version_run_id
        name = version_name(SLUG, 12)
        self.assertEqual(name, "astra_v12__github.com__acme__golden")
        self.assertEqual(version_run_id(SLUG, name), 12)
        for other in (collection_name(SLUG), version_name(SLUG + "__v3", 12), "astra_v1x__github.com__acme__golden",
                      None):
            self.assertIsNone(version_run_id(SLUG, other))

    def test_swap_is_one_step_and_the_live_version_is_never_deleted(self):
        alias = collection_name(SLUG)
        for run_id in (1, 2, 3):
            self.store.create(version_name(SLUG, run_id), 4)
        self.store.swap_alias(alias, version_name(SLUG, 1))
        self.store.swap_alias(alias, version_name(SLUG, 2))
        self.assertEqual(self.store.alias_target(alias), version_name(SLUG, 2))
        self.assertFalse(self.store.delete_version(SLUG, version_name(SLUG, 2)))
        self.assertEqual(self.store.drop_versions(SLUG, keep=None), [version_name(SLUG, 1), version_name(SLUG, 3)])
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, 2)])
        with self.assertRaises(ValueError):
            self.store.delete_version(SLUG, alias)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        use_temp_registry(self)
        self.store = QdrantStore(QdrantClient(":memory:"))
        self.embedder = FakeEmbedder()

    def run_pipeline(self, repo_dir=FIXTURE_REPO, embedder=None, store=None):
        run_id = runs.register_and_queue(REPO.ref, "https://github.com/acme/golden", REPO.branch, "env:X")
        runs.update_run(run_id, commit_sha=REPO.commit_sha)
        pipeline.run_ingestion(run_id, REPO, repo_dir, embedder or self.embedder, store or self.store)
        return runs.latest_run(SLUG)

    def test_end_to_end_ingest_and_hybrid_search(self):
        status = self.run_pipeline()
        self.assertEqual(status["state"], "done", status["error"])
        self.assertEqual(status["files_loaded"], 3)
        self.assertEqual(len(status["files_skipped"]), 2)
        self.assertEqual(status["chunks_stored"], status["chunks_total"])
        name = collection_name(SLUG)
        self.assertEqual(self.store.count(name), status["chunks_total"])

        hits = pipeline.search(SLUG, "BRD-HR-014 onboarding", embedder=self.embedder, store=self.store)
        self.assertEqual(hits[0]["path"], "project-data/hr/2024/onboarding.txt")
        self.assertEqual(hits[0]["embedding_model"], "fake-embedder")

        csv_hits = pipeline.search(SLUG, "Marketing conferences", file_type="csv",
                                   embedder=self.embedder, store=self.store)
        self.assertTrue(all(h["file_type"] == "csv" for h in csv_hits))
        hr_hits = pipeline.search(SLUG, "annual leave", folder_top="hr",
                                  embedder=self.embedder, store=self.store)
        self.assertTrue(all(h["folder_top"] == "hr" for h in hr_hits))

    def test_reingest_builds_a_new_version_and_swaps_the_alias(self):
        first = self.run_pipeline()
        alias = collection_name(SLUG)
        self.assertEqual(self.store.alias_target(alias), version_name(SLUG, first["run_id"]))
        self.assertEqual(first["collection"], version_name(SLUG, first["run_id"]))
        second = self.run_pipeline()
        self.assertEqual(self.store.alias_target(alias), version_name(SLUG, second["run_id"]))
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, second["run_id"])])  # old one dropped
        self.assertEqual(self.store.count(alias), second["chunks_total"])
        self.assertEqual(first["chunks_total"], second["chunks_total"])
        self.assertEqual(repos.get_repo(SLUG)["indexed"]["collection"], version_name(SLUG, second["run_id"]))

    def test_search_keeps_serving_the_old_index_throughout_a_rebuild(self):
        self.run_pipeline()
        seen, test = [], self

        class Watching(FakeEmbedder):
            def embed_passages(self, texts):
                seen.append(pipeline.search(SLUG, "annual leave", embedder=test.embedder, store=test.store))
                return super().embed_passages(texts)

        self.run_pipeline(embedder=Watching())
        self.assertTrue(seen)
        self.assertTrue(all(hits for hits in seen))  # never empty mid-rebuild

    def test_a_pre_alias_collection_is_replaced_by_the_alias(self):
        alias = collection_name(SLUG)
        self.store.create(alias, self.embedder.dense_dim)  # how P4 and earlier stored the index
        status = self.run_pipeline()
        self.assertNotIn(alias, self.store.collections())
        self.assertEqual(self.store.alias_target(alias), version_name(SLUG, status["run_id"]))
        self.assertTrue(pipeline.search(SLUG, "annual leave", embedder=self.embedder, store=self.store))

    def test_a_short_count_fails_the_run_and_keeps_the_old_index(self):
        good = self.run_pipeline()

        class Lossy(QdrantStore):
            def upsert(self, collection, chunks, dense, sparse):
                super().upsert(collection, chunks[:-1], dense[:-1], sparse[:-1])

        status = self.run_pipeline(store=Lossy(self.store.client))
        self.assertEqual(status["state"], "failed")
        self.assertIn("Index check failed", status["error"])
        self.assertEqual(self.store.alias_target(collection_name(SLUG)), version_name(SLUG, good["run_id"]))
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, good["run_id"])])

    def test_empty_project_data_is_done_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "project-data").mkdir()
            status = self.run_pipeline(Path(tmp))
        self.assertEqual(status["state"], "done")
        self.assertEqual(status["chunks_total"], 0)
        self.assertTrue(status["warnings"])

    def test_unreachable_qdrant_is_reported_as_failure(self):
        class Down(QdrantStore):
            def ping(self):
                raise AppError("Could not reach Qdrant.", 503)

        status = self.run_pipeline(store=Down(QdrantClient(":memory:")))
        self.assertEqual(status["state"], "failed")
        self.assertIn("Qdrant", status["error"])
        self.assertEqual(repos.get_repo(SLUG)["index_state"], "none")

    def test_failure_mid_rebuild_keeps_the_old_index_serving(self):
        good = self.run_pipeline()

        class Broken(FakeEmbedder):  # fails after the new version was created
            def embed_passages(self, texts):
                raise RuntimeError("model crashed")

        status = self.run_pipeline(embedder=Broken())
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["error"], "Unexpected error during ingestion (RuntimeError).")
        self.assertEqual(status["chunks_total"], good["chunks_total"])  # progress up to the failure is kept
        repo = repos.get_repo(SLUG)
        self.assertEqual(repo["indexed"]["run_id"], good["run_id"])
        self.assertEqual((repo["index_state"], repo["needs_rebuild"]), ("ready", False))
        self.assertEqual(self.store.alias_target(collection_name(SLUG)), version_name(SLUG, good["run_id"]))
        self.assertEqual(self.store.versions(SLUG), [version_name(SLUG, good["run_id"])])  # half-built one gone
        self.assertEqual(self.store.count(collection_name(SLUG)), good["chunks_total"])

    def test_done_run_records_the_indexed_commit(self):
        status = self.run_pipeline()
        repo = repos.get_repo(SLUG)
        self.assertEqual((repo["index_state"], repo["indexed"]["commit_sha"]), ("ready", REPO.commit_sha))
        self.assertEqual(status["started_at"] <= status["finished_at"], True)

    def test_search_without_index_or_query_errors(self):
        with self.assertRaises(AppError):
            pipeline.search(SLUG, "  ", embedder=self.embedder, store=self.store)
        with self.assertRaises(Exception):
            pipeline.search("acme", "nope", "x", embedder=self.embedder, store=self.store)


if __name__ == "__main__":
    unittest.main()
