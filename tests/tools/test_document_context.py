import unittest
from unittest import mock

from astra_rag.services.errors import AppError
from astra_rag.services.tools.document_context.handler import add_type_enum, get_document_context
from astra_rag.services.tools.document_context.schemas import DocumentContext, DocumentContextArgs

from .helpers import ARGS, FILES, HANDLER, PAT, REPO, TEMPLATES, fake_get_file


def run(request_type, templates=TEMPLATES, get_file=fake_get_file):
    args = DocumentContextArgs(**ARGS, request_type=request_type)
    with mock.patch(f"{HANDLER}.list_dir", return_value=templates), mock.patch(f"{HANDLER}.get_file", side_effect=get_file):
        return get_document_context(REPO, PAT, args)


class DocumentContextTests(unittest.TestCase):
    def test_each_type_and_sources(self):
        for rtype, body in (("BRD", "BRD TEMPLATE"), ("SPEC", "SPEC TEMPLATE")):
            ctx = run(rtype)
            self.assertEqual((ctx.policies, ctx.nomenclature, ctx.template), ("POLICIES", "NAMES", body))
            self.assertEqual([s.path for s in ctx.sources],
                             ["policies.md", "nomenclature.md", f"templates/{rtype.lower()}.md"])
            self.assertEqual(ctx.sources[0].sha, "sha-policies.md")
            DocumentContext.model_validate(ctx.model_dump())

    def test_case_insensitive_and_trimmed(self):
        self.assertEqual(run("  bRd ").request_type, "BRD")

    def test_alias(self):
        with mock.patch.dict("astra_rag.services.tools.document_context.handler.TEMPLATE_ALIASES", {"REQUIREMENTS": "BRD"}):
            ctx = run("requirements")
        self.assertEqual((ctx.request_type, ctx.template), ("BRD", "BRD TEMPLATE"))

    def test_unknown_type_lists_valid_types(self):
        with self.assertRaises(AppError) as cm:
            run("nope")
        self.assertEqual(cm.exception.status, 404)
        self.assertIn("BRD, SPEC", cm.exception.message)

    def test_empty_templates_folder(self):
        with self.assertRaises(AppError) as cm:
            run("BRD", templates=[])
        self.assertEqual(cm.exception.status, 404)
        self.assertIn("none found", cm.exception.message)

    def test_ambiguous_template(self):
        with self.assertRaises(AppError) as cm:
            run("BRD", templates=[{"name": "brd.md", "type": "file"}, {"name": "BRD.md", "type": "file"}])
        self.assertEqual(cm.exception.status, 409)
        self.assertIn("brd.md", cm.exception.message)
        self.assertIn("BRD.md", cm.exception.message)

    def test_missing_files_are_named(self):
        for missing in ("policies.md", "nomenclature.md", "templates/brd.md"):
            files = {k: v for k, v in FILES.items() if k != missing}

            def get_file(repo, path, token, files=files):
                if path not in files:
                    raise AppError(f"File '{path}' was not found in the repository.", 404)
                return {"path": path, "sha": "s", "content": files[path]}

            with self.assertRaises(AppError) as cm:
                run("BRD", get_file=get_file)
            self.assertEqual(cm.exception.status, 404)
            self.assertIn(missing, cm.exception.message)

    def test_path_comes_only_from_discovered_filename(self):
        paths = []

        def get_file(repo, path, token):
            paths.append(path)
            return fake_get_file(repo, path, token)

        with self.assertRaises(AppError):
            run("../../etc/passwd", get_file=get_file)
        self.assertEqual(paths, [])
        run("brd", get_file=get_file)
        self.assertIn("templates/brd.md", paths)

    def test_schema_hook_adds_enum_from_live_templates(self):
        schema = DocumentContextArgs.model_json_schema()
        with mock.patch(f"{HANDLER}.list_dir", return_value=TEMPLATES):
            add_type_enum(schema, REPO, PAT)
        self.assertEqual(schema["properties"]["request_type"]["enum"], ["BRD", "SPEC"])


if __name__ == "__main__":
    unittest.main()
