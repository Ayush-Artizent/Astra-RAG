import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from astra_rag import create_app
from astra_rag.services.catalog import CatalogCache, build_catalog, service
from astra_rag.services.catalog.live import AdapterReader
from astra_rag.services.context.selection import Request, select
from astra_rag.services.errors import AppError
from astra_rag.services.registry import repos, runs
from tests.helpers import use_temp_registry
from tests.test_catalog import make_repo
from tests.test_catalog_live import FakeAdapter
from tests.test_routes import SLUG, fake_adapter

POLICIES = """## Data handling
No card numbers.

## PCI
Follow PCI rules.

## Sign-off
Two approvers.

## Design checks
Review the architecture.

## Build notes
Tag releases.

## Tone
Be concise.
"""
MANIFEST = """
doc_types:
  BRD: {aliases: [business requirements]}
  SPEC: []
stages: [design, build]
tags: [payments, security]
rules:
  - {file: policies.md, section: Data handling, always: true}
  - {file: policies.md, section: PCI, applies_to: {tags: [payments]}, priority: 10}
  - {file: policies.md, section: Sign-off, applies_to: {doc_types: [BRD]}, priority: 20}
  - {file: policies.md, section: Design checks, applies_to: {doc_types: [BRD], stages: [design]}, priority: 20}
  - {file: policies.md, section: Build notes, applies_to: {stages: [build]}}
templates:
  - {file: templates/brd/payments.md, applies_to: {tags: [payments]}}
  - {file: templates/brd/payments-design.md, applies_to: {tags: [payments], stages: [design]}}
"""
FILES = {
    "policies.md": POLICIES, "nomenclature.md": "# Naming\nBRD-001\n", "golden.yaml": MANIFEST,
    "templates/brd.md": "# BRD\n## Scope\n## Risks\n",
    "templates/brd/payments.md": "# BRD payments\n## Scope\n## Payment Flows\n",
    "templates/brd/payments-design.md": "# BRD payments design\n## Scope\n## Payment Flows\n## Architecture\n",
    "templates/spec/api.md": "# API\n## Endpoints\n", "templates/spec/ui.md": "# UI\n## Screens\n",
}


def catalog_for(files=None):
    root = Path(tempfile.mkdtemp())
    return build_catalog(make_repo(root, files or FILES))


def titles(selection):
    return [s.rule.section.title for s in selection.rules]


class RuleSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog_for()

    def pick(self, doc_type="BRD", stage=None, tags=()):
        return select(self.catalog, Request(doc_type, stage, tuple(tags)))

    def test_always_rules_come_first_then_scope_by_priority_file_section(self):
        picked = self.pick("BRD", "design", ["payments"])
        self.assertEqual(titles(picked), ["Data handling", "PCI", "Sign-off", "Design checks"])
        self.assertEqual([s.matched_on for s in picked.rules],
                         ["always", "scope: tags", "scope: doc_types", "scope: doc_types, stages"])

    def test_every_dimension_a_scope_lists_must_match(self):
        self.assertEqual(titles(self.pick("BRD", "build")), ["Data handling", "Sign-off", "Build notes"])
        self.assertEqual(titles(self.pick("SPEC", "design")), ["Data handling"])

    def test_a_dimension_the_request_omits_does_not_match(self):
        self.assertNotIn("Design checks", titles(self.pick("BRD", None)))
        self.assertNotIn("PCI", titles(self.pick("BRD", "design", [])))

    def test_tags_match_on_any_overlap_ignoring_case(self):
        self.assertIn("PCI", titles(self.pick("BRD", None, ["Security", " PAYMENTS "])))

    def test_untagged_sections_are_never_selected_and_are_counted(self):
        picked = self.pick("BRD", "design", ["payments"])
        self.assertNotIn("Tone", titles(picked))
        unscoped = [w for w in picked.warnings if w.code == "unscoped_rules"]
        self.assertEqual(len(unscoped), 1)
        self.assertIn("2 rule section", unscoped[0].message)  # Tone, and the Naming section of nomenclature.md

    def test_doc_type_is_case_insensitive_and_accepts_an_alias(self):
        self.assertEqual(self.pick("brd").doc_type, "BRD")
        self.assertEqual(self.pick("Business Requirements").doc_type, "BRD")

    def test_unknown_or_blank_doc_type_lists_the_known_ones(self):
        for bad in ("memo", "", "   "):
            with self.assertRaises(AppError) as ctx:
                self.pick(bad)
            self.assertEqual(ctx.exception.status, 422)
            self.assertIn("BRD", ctx.exception.message)


class TemplateVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog_for()

    def pick(self, doc_type, stage=None, tags=()):
        return select(self.catalog, Request(doc_type, stage, tuple(tags)))

    def test_default_when_no_scoped_variant_matches(self):
        t = self.pick("BRD", "build", ["security"]).template
        self.assertEqual((t.path, t.default), ("templates/brd.md", True))

    def test_scoped_variant_beats_the_default(self):
        self.assertEqual(self.pick("BRD", None, ["payments"]).template.path, "templates/brd/payments.md")

    def test_most_specific_variant_wins(self):
        self.assertEqual(self.pick("BRD", "design", ["payments"]).template.path,
                         "templates/brd/payments-design.md")
        self.assertEqual(self.pick("BRD", "build", ["payments"]).template.path, "templates/brd/payments.md")

    def test_the_whole_template_text_is_returned(self):
        self.assertEqual(self.pick("BRD").template.text, FILES["templates/brd.md"])

    def test_no_match_and_no_default_gives_no_template_and_a_warning(self):
        picked = self.pick("SPEC")
        self.assertIsNone(picked.template)
        self.assertIn("no_matching_template", [w.code for w in picked.warnings])

    def test_a_type_with_no_template_warns(self):
        files = {k: v for k, v in FILES.items() if not k.startswith("templates/spec")}
        picked = select(catalog_for(files), Request("SPEC"))
        self.assertIsNone(picked.template)
        self.assertIn("no_template", [w.code for w in picked.warnings])


class NoManifestTests(unittest.TestCase):
    def test_conventions_only_select_nothing_and_warn(self):
        files = {k: v for k, v in FILES.items() if k != "golden.yaml"}
        picked = select(catalog_for(files), Request("BRD", "design", ("payments",)))
        self.assertEqual(picked.rules, [])
        self.assertEqual(picked.template.path, "templates/brd.md")
        self.assertIn("unscoped_rules", [w.code for w in picked.warnings])


class ContextPreviewRouteTests(unittest.TestCase):
    def setUp(self):
        use_temp_registry(self)
        service._cache = CatalogCache()
        self.client = TestClient(create_app())
        self.adapter = FakeAdapter(FILES)
        runs.register_and_queue(fake_adapter().ref, "https://github.com/acme/golden", "main", "ref")
        repos.bind_project("proj-1", SLUG)
        for target, new in (("adapter_for", mock.Mock(return_value=self.adapter)),
                            ("token_store.get_token", mock.Mock(return_value="tok"))):
            patcher = mock.patch(f"astra_rag.services.catalog.service.{target}", new)
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, **body):
        return self.client.post("/api/context/preview", json={"project_id": "proj-1", **body})

    def test_returns_rules_and_the_whole_template(self):
        data = self.post(doc_type="brd", stage="design", tags=["payments"]).json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["request"], {"doc_type": "BRD", "stage": "design", "tags": ["payments"]})
        self.assertEqual(data["snapshot"], {"rules_commit": "c1"})
        self.assertFalse(data["stale"])
        self.assertEqual([r["section"] for r in data["rules"]], ["Data handling", "PCI", "Sign-off", "Design checks"])
        first = data["rules"][0]
        self.assertIn("No card numbers.", first["text"])
        self.assertEqual((first["matched_on"], first["priority"]), ("always", 100))
        self.assertIn("/acme/golden/blob/c1/policies.md#L", first["source_url"])
        t = data["template"]
        self.assertEqual((t["path"], t["variant"]), ("templates/brd/payments-design.md", "payments-design"))
        self.assertEqual(t["text"], FILES["templates/brd/payments-design.md"])
        self.assertEqual(t["sections"], ["BRD payments design", "Scope", "Payment Flows", "Architecture"])

    def test_host_down_serves_the_cached_catalog_marked_stale(self):
        self.post(doc_type="BRD")
        self.adapter.fail = AppError("Could not reach the host.", 502)
        data = self.post(doc_type="BRD").json()
        self.assertTrue(data["stale"])
        self.assertTrue(data["template"]["text"])

    def test_errors(self):
        self.assertEqual(self.post(doc_type="memo").status_code, 422)
        self.assertEqual(self.client.post("/api/context/preview", json={"project_id": "proj-1"}).status_code, 422)
        self.assertEqual(self.client.post("/api/context/preview",
                                          json={"project_id": "other", "doc_type": "BRD"}).status_code, 404)

    def test_token_is_never_returned(self):
        self.assertNotIn('"tok"', self.post(doc_type="BRD").text)


if __name__ == "__main__":
    unittest.main()
