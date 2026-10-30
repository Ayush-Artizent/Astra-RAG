import tempfile
import unittest
from pathlib import Path

from astra_rag.services.catalog import CatalogCache, LocalCloneReader, build_catalog
from astra_rag.services.catalog.manifest import parse_manifest
from astra_rag.services.catalog.sections import split_sections

POLICIES = """Intro line.

## Data handling
Never store card numbers.

### Retention
Keep 7 years.

## Tone
Be concise.

```
## not a heading
```
"""
NOMENCLATURE = "# Naming\n\nBRD-<project>-<nnn>\n"
MANIFEST = """
version: 1
doc_types:
  BRD: {aliases: [business requirements]}
  SPEC: []
stages: [design, build]
tags: [payments]
rules:
  - file: policies.md
    section: Data handling
    always: true
  - file: policies.md
    section: Tone
    applies_to: {doc_types: [BRD], stages: [design]}
    priority: 5
  - file: policies.md
    section: Missing section
    always: true
  - file: nope.md
    always: true
templates:
  - type: SPEC
    variant: api
    default: true
    applies_to: {tags: [payments]}
"""


def make_repo(root: Path, files: dict[str, str]) -> LocalCloneReader:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "project-data").mkdir(exist_ok=True)
    return LocalCloneReader(root, "sha1")


BASE = {
    "policies.md": POLICIES, "nomenclature.md": NOMENCLATURE,
    "templates/brd.md": "# BRD\n## Scope\n## Risks\n", "templates/spec/api.md": "# API\n## Endpoints\n",
    "templates/spec/ui.md": "# UI\n## Screens\n",
}


class SectionTests(unittest.TestCase):
    def test_sections_paths_ids_and_fences(self):
        secs = split_sections("policies.md", POLICIES)
        self.assertEqual([s.title for s in secs], ["Preamble", "Data handling", "Retention", "Tone"])
        self.assertEqual(secs[2].heading_path, ("Data handling", "Retention"))
        self.assertEqual(secs[2].id, "policies.md#data-handling/retention")
        self.assertIn("not a heading", secs[3].text)

    def test_duplicate_headings_get_distinct_ids(self):
        secs = split_sections("a.md", "## A\nx\n## A\ny\n")
        self.assertEqual([s.id for s in secs], ["a.md#a", "a.md#a-2"])

    def test_front_matter_is_not_a_section_and_lines_still_match(self):
        text = "---\nversion: 1\n# a yaml comment\n---\n# Title\n\n## Rule\nbody\n"
        secs = split_sections("r.md", text)
        self.assertEqual([s.title for s in secs], ["Rule"])
        self.assertEqual(secs[0].start_line, 7)  # counted in the original file

    def test_leading_horizontal_rule_is_not_front_matter(self):
        secs = split_sections("r.md", "---\nIntro text\n---\n## Rule\nbody\n")
        self.assertEqual([s.title for s in secs], ["Preamble", "Rule"])

    def test_heading_without_body_is_skipped(self):
        secs = split_sections("a.md", "# Top\n## Child\ntext\n")
        self.assertEqual([s.heading_path for s in secs], [("Top", "Child")])


class ManifestTests(unittest.TestCase):
    def test_absent_is_not_a_warning(self):
        m, w = parse_manifest(None)
        self.assertFalse(m.present)
        self.assertEqual(w, [])

    def test_bad_yaml_and_wrong_shape(self):
        for text in ("a: [unclosed", "- just\n- a list"):
            m, w = parse_manifest(text)
            self.assertFalse(m.present)
            self.assertEqual(w[0].code, "manifest_invalid")

    def test_wrong_field_types_warn_and_continue(self):
        m, w = parse_manifest("stages: 5\ntags: {a: 1}\nrules: nope\ntemplates: [1]\nversion: 9\n")
        self.assertTrue(m.present)
        codes = [x.code for x in w]
        self.assertIn("manifest_version", codes)
        self.assertEqual(m.rules, [])
        self.assertEqual(m.stages, ("5",))

    def test_doc_types_aliases(self):
        m, _ = parse_manifest("doc_types:\n  BRD: {aliases: [business requirements]}\n  SPEC: [tech spec]\n")
        self.assertEqual(m.doc_types, {"BRD": ("business requirements",), "SPEC": ("tech spec",)})


class CatalogTests(unittest.TestCase):
    def build(self, files, manifest=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        all_files = dict(files)
        if manifest is not None:
            all_files["golden.yaml"] = manifest
        return build_catalog(make_repo(Path(tmp.name), all_files))

    def codes(self, cat):
        return [w.code for w in cat.warnings]

    def test_no_manifest_uses_conventions_and_warns(self):
        cat = self.build(BASE)
        self.assertFalse(cat.manifest_present)
        self.assertIn("no_always_rules", self.codes(cat))
        self.assertTrue(all(r.selection == "relevance" for r in cat.rules))
        self.assertEqual(sorted(cat.doc_types), ["BRD", "SPEC"])
        brd = [t for t in cat.templates if t.doc_type == "BRD"][0]
        self.assertTrue(brd.default)
        self.assertEqual(brd.headings, ("BRD", "Scope", "Risks"))
        # SPEC has two variants and no manifest default
        self.assertIn("no_default_variant", self.codes(cat))

    def test_manifest_scopes_and_warnings(self):
        cat = self.build(BASE, MANIFEST)
        by = {r.section.id: r for r in cat.rules}
        self.assertEqual(by["policies.md#data-handling"].selection, "always")
        self.assertEqual(by["policies.md#data-handling/retention"].selection, "always")  # child inherits
        tone = by["policies.md#tone"]
        self.assertEqual((tone.selection, tone.priority), ("scope", 5))
        self.assertEqual(tone.scope.doc_types, ("BRD",))
        self.assertEqual(by["nomenclature.md#naming"].selection, "relevance")
        codes = self.codes(cat)
        self.assertIn("rule_section_missing", codes)
        self.assertIn("rule_file_missing", codes)
        self.assertNotIn("no_always_rules", codes)
        self.assertNotIn("no_default_variant", codes)
        api = [t for t in cat.templates if t.variant == "api"][0]
        self.assertTrue(api.default)
        self.assertEqual(api.scope.tags, ("payments",))

    def test_unknown_doc_type_and_aliases(self):
        files = dict(BASE, **{"templates/risk-log.md": "# Risks\n## A\n"})
        cat = self.build(files, MANIFEST)
        self.assertIn("unknown_doc_type", self.codes(cat))
        alias = self.build({"policies.md": POLICIES, "nomenclature.md": NOMENCLATURE,
                            "templates/business requirements.md": "# B\n## S\n"}, MANIFEST)
        self.assertEqual([t.doc_type for t in alias.templates], ["BRD"])

    def test_rules_folder_and_empty_templates(self):
        files = {"policies.md": POLICIES, "nomenclature.md": NOMENCLATURE, "rules/security/r.md": "## R-1\nText\n"}
        cat = self.build(files)
        self.assertIn("rules/security/r.md", {r.section.file for r in cat.rules})
        self.assertEqual(cat.templates, [])

    def test_missing_required_items_are_warnings(self):
        cat = self.build({"policies.md": POLICIES})
        self.assertIn("required_missing", self.codes(cat))

    def test_to_dict_hides_text_by_default(self):
        cat = self.build(BASE, MANIFEST)
        self.assertNotIn("text", cat.to_dict()["rules"][0])
        self.assertIn("text", cat.to_dict(include_text=True)["rules"][0])
        self.assertEqual(cat.to_dict()["head_sha"], "sha1")


class CacheTests(unittest.TestCase):
    def test_rebuilds_only_when_head_changes_and_reuses_bodies(self):
        class Reader:
            def __init__(self):
                self.sha, self.reads = "a", 0
            def head_sha(self): return self.sha
            def list_dir(self, path):
                return [{"name": "policies.md", "type": "file", "sha": "b1"},
                        {"name": "nomenclature.md", "type": "file", "sha": "b2"}] if path == "" else []
            def read_file(self, path):
                self.reads += 1
                return "## Rule\nbody\n"

        reader, cache = Reader(), CatalogCache()
        first = cache.get("k", reader)
        reads = reader.reads
        self.assertIs(cache.get("k", reader), first)
        self.assertEqual(reader.reads, reads)
        reader.sha = "b"  # new commit, same blobs -> new catalog, no body re-reads
        second = cache.get("k", reader)
        self.assertIsNot(second, first)
        self.assertEqual(second.head_sha, "b")
        self.assertEqual(reader.reads, reads)


class LocalReaderTests(unittest.TestCase):
    def test_ignores_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = make_repo(Path(tmp), {"policies.md": "x"})
            self.assertIsNone(reader.read_file("../secret"))
            self.assertEqual(reader.list_dir("../"), [])
            self.assertEqual(reader.read_file("policies.md"), "x")


if __name__ == "__main__":
    unittest.main()
