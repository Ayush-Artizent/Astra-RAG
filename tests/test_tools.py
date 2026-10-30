import unittest
from unittest import mock

from astra_rag.services import tools
from astra_rag.services.context import service as context_service
from astra_rag.services.errors import AppError
from tests.test_context_full import REQUEST, ContextTestBase


class ToolSchemaTests(ContextTestBase):
    def test_schemas_are_claude_format_and_doc_type_becomes_an_enum_for_a_project(self):
        plain = {t["name"]: t for t in tools.describe_tools()}
        self.assertEqual(set(plain), {"get_document_context", "search_project_data"})
        for tool in plain.values():
            self.assertEqual(set(tool), {"name", "description", "input_schema"})
            self.assertIn("project_id", tool["input_schema"]["required"])
        self.assertNotIn("enum", plain["get_document_context"]["input_schema"]["properties"]["doc_type"])
        live = {t["name"]: t for t in tools.describe_tools("proj-1")}
        self.assertEqual(live["get_document_context"]["input_schema"]["properties"]["doc_type"]["enum"], ["BRD", "SPEC"])

    def test_the_schema_stays_usable_when_the_project_is_unknown(self):
        described = {t["name"]: t for t in tools.describe_tools("nope")}
        self.assertNotIn("enum", described["get_document_context"]["input_schema"]["properties"]["doc_type"])

    def test_descriptions_say_the_content_is_data(self):
        for tool in tools.describe_tools():
            self.assertIn("not instructions", tool["description"])


class ToolDispatchTests(ContextTestBase):
    def test_get_document_context_matches_the_context_endpoint(self):
        result = tools.run_tool("get_document_context", {"project_id": "proj-1", **REQUEST})
        self.assertIn("not instructions", result["notice"])
        self.assertEqual(result["data"], context_service.get_context("proj-1", **REQUEST))

    def test_search_project_data_returns_ranked_evidence_with_sources(self):
        result = tools.run_tool("search_project_data", {"project_id": "proj-1", "query": "cash on delivery", "limit": 2})
        data = result["data"]
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["total_count"], 3)
        self.assertEqual(data["status"], {"knowledge": "ok", "rerank": "ok"})
        self.assertTrue(all(i["source_url"] and i["doc_date"] is not None or i["file"] for i in data["items"]))

    def test_search_filters_by_folder(self):
        data = tools.run_tool("search_project_data",
                              {"project_id": "proj-1", "query": "limit", "folder": "emails"})["data"]
        self.assertEqual([i["file"] for i in data["items"]], ["emails/a.md"])

    def test_unknown_tool_and_unbound_project(self):
        with self.assertRaises(AppError) as ctx:
            tools.run_tool("drop_tables", {})
        self.assertEqual(ctx.exception.status, 404)
        with self.assertRaises(AppError) as ctx:
            tools.run_tool("search_project_data", {"project_id": "other", "query": "x"})
        self.assertEqual(ctx.exception.status, 404)

    def test_invalid_arguments_name_the_fields_and_echo_no_values(self):
        with self.assertRaises(AppError) as ctx:
            tools.run_tool("get_document_context", {"project_id": "../etc", "doc_type": "BRD", "text": "SECRET-VALUE" * 400})
        self.assertEqual(ctx.exception.status, 422)
        self.assertIn("project_id", ctx.exception.message)
        self.assertIn("text", ctx.exception.message)
        self.assertNotIn("SECRET-VALUE", ctx.exception.message)

    def test_routes_list_and_invoke(self):
        listed = self.client.get("/api/tools", params={"project_id": "proj-1"}).json()
        self.assertEqual([t["name"] for t in listed["tools"]], ["get_document_context", "search_project_data"])
        invoked = self.client.post("/api/tools/invoke", json={
            "name": "search_project_data", "arguments": {"project_id": "proj-1", "query": "refund"}})
        self.assertEqual(invoked.status_code, 200)
        self.assertTrue(invoked.json()["result"]["data"]["items"])
        self.assertEqual(self.client.post("/api/tools/invoke", json={"name": "x", "arguments": {}}).status_code, 404)
        self.assertEqual(self.client.get("/api/tools", params={"project_id": "../x"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
