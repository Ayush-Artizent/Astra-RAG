import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from astra_rag import create_app
from astra_rag.services.errors import AppError
from astra_rag.services.tools import registry
from astra_rag.services.tools.base import to_claude, to_mcp
from astra_rag.services.tools.document_context import tool as doc_tool
from astra_rag.services.tools.document_context.schemas import DocumentContext

from .helpers import ARGS, CREDS, HANDLER, PAT, REPO, TEMPLATES, fake_get_file


def enum(entry):
    return entry["input_schema"]["properties"]["request_type"].get("enum")


class SchemaTests(unittest.TestCase):
    def test_claude_and_mcp_renderings(self):
        claude, mcp = to_claude(doc_tool), to_mcp(doc_tool)
        self.assertEqual(claude["name"], "get_document_context")
        self.assertEqual(sorted(claude["input_schema"]["required"]), ["name", "owner", "request_type"])
        self.assertNotIn("title", claude["input_schema"])
        self.assertEqual(mcp["inputSchema"], claude["input_schema"])
        self.assertIn("sources", mcp["outputSchema"]["properties"])
        self.assertIn("not instructions", claude["description"])

    def test_describe_tools_enum_only_with_creds_and_survives_github_failure(self):
        self.assertIsNone(enum(registry.describe_tools()[0]))
        with mock.patch(f"{HANDLER}.list_dir", return_value=TEMPLATES):
            typed = registry.describe_tools((REPO, PAT))[0]
        self.assertEqual(enum(typed), ["BRD", "SPEC"])
        self.assertIn("output_schema", typed)
        with mock.patch(f"{HANDLER}.list_dir", side_effect=AppError("down", 502)):
            self.assertIsNone(enum(registry.describe_tools((REPO, PAT))[0]))


class DispatcherTests(unittest.TestCase):
    def test_unknown_tool(self):
        with self.assertRaises(AppError) as cm:
            registry.run_tool("other", {})
        self.assertEqual(cm.exception.status, 400)

    def test_invalid_arguments_message_has_field_names_only(self):
        bad = ({}, {**ARGS, "request_type": ""}, {**ARGS, "request_type": "x" * 65},
               {**ARGS, "request_type": 5}, {"owner": "../x", "name": "golden", "request_type": "BRD"})
        for args in bad:
            with self.assertRaises(AppError) as cm:
                registry.run_tool("get_document_context", args)
            self.assertEqual(cm.exception.status, 400)
            self.assertNotIn("xxxx", cm.exception.message)
            self.assertNotIn("../x", cm.exception.message)
        with self.assertRaises(AppError) as cm:
            registry.run_tool("get_document_context", {"owner": "../x", "name": "g", "request_type": "BRD"})
        self.assertIn("owner", cm.exception.message)

    def test_valid_call_resolves_credentials_by_owner_and_name(self):
        with mock.patch(CREDS, return_value=(REPO, PAT)) as creds, \
                mock.patch(f"{HANDLER}.list_dir", return_value=TEMPLATES), mock.patch(f"{HANDLER}.get_file", side_effect=fake_get_file):
            result = registry.run_tool("get_document_context", {**ARGS, "request_type": "spec"})
        creds.assert_called_once_with("acme", "golden")
        DocumentContext.model_validate(result)
        self.assertNotIn(PAT, json.dumps(result))

    def test_not_connected_is_reported(self):
        with mock.patch(CREDS, side_effect=AppError("No saved connection for acme/golden.", 404)):
            with self.assertRaises(AppError) as cm:
                registry.run_tool("get_document_context", {**ARGS, "request_type": "spec"})
        self.assertEqual(cm.exception.status, 404)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.call = {"name": "get_document_context"}

    def test_invoke_takes_owner_name_not_credentials(self):
        with mock.patch(CREDS, return_value=(REPO, PAT)), \
                mock.patch(f"{HANDLER}.list_dir", return_value=TEMPLATES), mock.patch(f"{HANDLER}.get_file", side_effect=fake_get_file):
            res = self.client.post("/api/tools/invoke", json={**self.call, "arguments": {**ARGS, "request_type": "brd"}})
            bad = self.client.post("/api/tools/invoke", json={**self.call, "arguments": {}})
            unknown = self.client.post("/api/tools/invoke", json={**self.call, "arguments": {**ARGS, "request_type": "zzz"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["result"]["template"], "BRD TEMPLATE")
        self.assertNotIn(PAT, res.text)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(unknown.status_code, 404)

    def test_invoke_for_unconnected_repo_is_404(self):
        with mock.patch(CREDS, side_effect=AppError("No saved connection for acme/golden.", 404)):
            res = self.client.post("/api/tools/invoke", json={**self.call, "arguments": {**ARGS, "request_type": "brd"}})
        self.assertEqual(res.status_code, 404)

    def test_tools_endpoint_lists_schema_with_optional_enum(self):
        plain = self.client.get("/api/tools").json()["tools"][0]
        self.assertIsNone(enum(plain))
        with mock.patch(CREDS, return_value=(REPO, PAT)), mock.patch(f"{HANDLER}.list_dir", return_value=TEMPLATES):
            typed = self.client.get("/api/tools", params=ARGS).json()["tools"][0]
        self.assertEqual(enum(typed), ["BRD", "SPEC"])


if __name__ == "__main__":
    unittest.main()
