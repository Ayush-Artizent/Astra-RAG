import unittest

import httpx

from astra_mcp.doc_client import DocClient, PlaneError
from astra_mcp.render import hide_project_id, to_mcp_tool

from .fake_plane import DOC_TOOL, NOTICE, FakeDocPlane, a_config


class RenderTests(unittest.TestCase):
    def test_project_id_is_hidden_from_properties_and_required(self):
        schema = hide_project_id(DOC_TOOL["input_schema"])
        self.assertNotIn("project_id", schema["properties"])
        self.assertEqual(schema["required"], ["doc_type", "text"])
        # Everything else is the plane's, untouched.
        self.assertEqual(schema["properties"]["doc_type"]["enum"], ["BRD", "SPEC"])
        self.assertEqual(schema["type"], "object")

    def test_required_disappears_when_only_the_project_was_required(self):
        schema = hide_project_id({"type": "object", "properties": {"project_id": {}}, "required": ["project_id"]})
        self.assertNotIn("required", schema)

    def test_the_plane_entry_is_not_mutated(self):
        to_mcp_tool(DOC_TOOL)
        self.assertIn("project_id", DOC_TOOL["input_schema"]["properties"])

    def test_entry_becomes_an_mcp_tool(self):
        tool = to_mcp_tool(DOC_TOOL)
        self.assertEqual(tool.name, "get_document_context")
        self.assertEqual(tool.description, DOC_TOOL["description"])
        self.assertNotIn("project_id", tool.input_schema["properties"])


class DocClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plane = FakeDocPlane()
        self.client = DocClient(a_config(), self.plane.client())

    async def test_list_tools_asks_for_this_project(self):
        tools = await self.client.list_tools()
        self.assertEqual(tools, [DOC_TOOL])
        self.assertEqual(self.plane.requests[-1].url.params["project_id"], "devx-123")

    async def test_invoke_injects_the_bound_project(self):
        await self.client.invoke("get_document_context", {"doc_type": "BRD", "text": "refunds"})
        body = self.plane.last_body()
        self.assertEqual(body["name"], "get_document_context")
        self.assertEqual(body["arguments"]["project_id"], "devx-123")
        self.assertEqual(body["arguments"]["doc_type"], "BRD")

    async def test_a_caller_cannot_choose_another_project(self):
        await self.client.invoke("get_document_context", {"project_id": "someone-else"})
        self.assertEqual(self.plane.last_body()["arguments"]["project_id"], "devx-123")

    async def test_invoke_returns_the_notice_and_data(self):
        result = await self.client.invoke("get_document_context", {})
        self.assertEqual(result["notice"], NOTICE)
        self.assertEqual(result["data"], {"rules": []})

    async def test_an_app_error_message_reaches_the_caller(self):
        self.plane.error = (404, "This project is not bound to a repository.")
        with self.assertRaises(PlaneError) as caught:
            await self.client.list_tools()
        self.assertEqual(str(caught.exception), "This project is not bound to a repository.")

    async def test_an_unreachable_plane_says_so_without_leaking_the_url(self):
        self.plane.raises = httpx.ConnectError("[Errno 111] Connection refused to http://127.0.0.1:5000")
        with self.assertRaises(PlaneError) as caught:
            await self.client.list_tools()
        message = str(caught.exception)
        self.assertIn("could not be reached", message)
        self.assertIn("ConnectError", message)
        self.assertNotIn("127.0.0.1", message)

    async def test_a_reply_that_is_not_json_is_reported_safely(self):
        self.plane.raw = (502, "<html>gateway</html>")
        with self.assertRaises(PlaneError) as caught:
            await self.client.list_tools()
        message = str(caught.exception)
        self.assertIn("502", message)
        self.assertNotIn("gateway", message)


if __name__ == "__main__":
    unittest.main()
