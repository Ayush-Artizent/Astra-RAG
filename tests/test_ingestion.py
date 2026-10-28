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
from astra_rag.services.ingestion.store import QdrantStore, collection_name, point_id
from astra_rag.services.ingestion.tokens import count_tokens

REPO = RepoContext("github.com", "acme", "golden", "main", "abc123def456")

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
        self.assertIn("## B", "\n".join(c.text for c in chunks))  # tiny sections merge, text is kept

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

    def test_heading_is_never_orphaned_at_end_of_chunk(self):
        text = "# T\n\n" + "para " * 330 + "\n\n## Next\n\nshort body\n"
        chunks = chunk_markdown(text)
        for c in chunks[:-1]:
            self.assertFalse(c.text.rstrip().splitlines()[-1].startswith("#"))

    def test_hash_inside_code_fence_is_not_a_heading(self):
        chunks = chunk_markdown("# T\n\n```bash\n# just a comment\n```\n")
        self.assertEqual(chunks[0].heading_path, ("T",))


class CsvChunkerTests(unittest.TestCase):
    def test_summary_plus_row_chunks_with_header_repeated(self):
        data = "id,name\n" + "\n".join(f"{i},{'x' * 60}" for i in range(1, 200))
        chunks, warnings = chunk_csv(data, "t.csv")
        self.assertEqual(warnings, [])
        self.assertEqual(chunks[0].kind, "csv_summary")
        rows = chunks[1:]
        self.assertGreater(len(rows), 1)
        self.assertTrue(all(c.text.startswith("Columns: id, name") for c in rows))
        self.assertEqual(rows[0].extra["row_start"], 1)
        self.assertEqual(rows[-1].extra["row_end"], 199)
        for a, b in zip(rows, rows[1:]):
            self.assertEqual(a.extra["row_end"] + 1, b.extra["row_start"])

    def test_semicolon_delimiter_and_blank_cells(self):
        chunks, _ = chunk_csv("a;b\n1;\n2;two\n", "t.csv")
        text = chunks[1].text
        self.assertIn("a: 1", text)
        self.assertNotIn("b: \n", text)
        self.assertIn("b: two", text)

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
        rows = [c for c in chunks if c.payload["chunk_kind"] == "csv_rows"][0].payload
        self.assertEqual((rows["row_start"], rows["row_end"]), (1, 3))
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


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.store = QdrantStore(QdrantClient(":memory:"))
        self.embedder = FakeEmbedder()

    def run_pipeline(self, repo_dir=FIXTURE_REPO):
        pipeline.mark_queued(REPO)
        pipeline.run_ingestion(REPO, repo_dir, self.embedder, self.store)
        return pipeline.get_status("acme", "golden")

    def test_end_to_end_ingest_and_hybrid_search(self):
        status = self.run_pipeline()
        self.assertEqual(status["state"], "done", status["error"])
        self.assertEqual(status["files_loaded"], 3)
        self.assertEqual(len(status["files_skipped"]), 2)
        self.assertEqual(status["chunks_stored"], status["chunks_total"])
        name = collection_name("acme", "golden")
        self.assertEqual(self.store.count(name), status["chunks_total"])

        hits = pipeline.search("acme", "golden", "BRD-HR-014 onboarding", embedder=self.embedder, store=self.store)
        self.assertEqual(hits[0]["path"], "project-data/hr/2024/onboarding.txt")
        self.assertEqual(hits[0]["embedding_model"], "fake-embedder")

        csv_hits = pipeline.search("acme", "golden", "Marketing conferences", file_type="csv",
                                   embedder=self.embedder, store=self.store)
        self.assertTrue(all(h["file_type"] == "csv" for h in csv_hits))
        hr_hits = pipeline.search("acme", "golden", "annual leave", folder_top="hr",
                                  embedder=self.embedder, store=self.store)
        self.assertTrue(all(h["folder_top"] == "hr" for h in hr_hits))

    def test_reingest_replaces_the_collection(self):
        first = self.run_pipeline()
        second = self.run_pipeline()
        self.assertEqual(self.store.count(collection_name("acme", "golden")), second["chunks_total"])
        self.assertEqual(first["chunks_total"], second["chunks_total"])

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

        pipeline.mark_queued(REPO)
        pipeline.run_ingestion(REPO, FIXTURE_REPO, self.embedder, Down(QdrantClient(":memory:")))
        status = pipeline.get_status("acme", "golden")
        self.assertEqual(status["state"], "failed")
        self.assertIn("Qdrant", status["error"])

    def test_search_without_index_or_query_errors(self):
        with self.assertRaises(AppError):
            pipeline.search("acme", "golden", "  ", embedder=self.embedder, store=self.store)
        with self.assertRaises(Exception):
            pipeline.search("acme", "nope", "x", embedder=self.embedder, store=self.store)


if __name__ == "__main__":
    unittest.main()
