"""Splitting a tool result into the parts the page shows, and the endpoint that returns them."""
import json
import unittest

from fastapi.testclient import TestClient

from astra_mcp.demo import create_app
from astra_mcp.demo.service import kind_of, split_result

from ..mcp.fake_plane import a_config
from .test_routes import StubSession

NOTE = "This project's code index is not ready, so there are no code results yet."
PAYLOAD = {"plane_status": "not_ready", "results": []}


def result(*texts, is_error=False):
    return {"content": [{"type": "text", "text": t} for t in texts], "isError": is_error}


class SplitTests(unittest.TestCase):
    def test_a_lone_block_is_the_payload_with_no_note(self):
        out = split_result("find_callers", result(json.dumps(PAYLOAD)))
        self.assertIsNone(out["note"])
        self.assertEqual(out["payload"], PAYLOAD)
        self.assertFalse(out["is_error"])

    def test_two_blocks_are_a_note_then_the_payload(self):
        out = split_result("find_callers", result(NOTE, json.dumps(PAYLOAD)))
        self.assertEqual(out["note"], NOTE)
        self.assertEqual(out["payload"], PAYLOAD)

    def test_a_refusal_keeps_its_message_where_json_would_be(self):
        out = split_result("find_callers", result("callers needs exactly 1 symbol", is_error=True))
        self.assertTrue(out["is_error"])
        self.assertIsNone(out["payload"])
        self.assertEqual(out["text"], "callers needs exactly 1 symbol")

    def test_an_empty_result_does_not_raise(self):
        out = split_result("find_callers", {})
        self.assertIsNone(out["payload"])
        self.assertEqual(out["text"], "")

    def test_the_kind_picks_the_renderer(self):
        self.assertEqual(kind_of("find_callers"), "code")
        self.assertEqual(kind_of("trace_flow"), "code")
        self.assertEqual(kind_of("code_index_status"), "status")
        self.assertEqual(kind_of("get_document_context"), "document")
        self.assertEqual(kind_of("search_project_data"), "document")


class CallingSession(StubSession):
    def __init__(self, reply=None, fails=None):
        super().__init__()
        self._reply = reply or result(NOTE, json.dumps(PAYLOAD))
        self._call_fails = fails
        self.called = None

    def call_tool(self, name, arguments):
        from astra_mcp.demo.session import SessionError
        self.called = (name, arguments)
        if self._call_fails:
            raise SessionError(self._call_fails)
        return self._reply


def a_client(session):
    return TestClient(create_app(a_config(doc_url="http://127.0.0.1:9", code_url="http://127.0.0.1:9",
                                          timeout_ms=500), session))


class CallEndpointTests(unittest.TestCase):
    def test_it_passes_the_arguments_through_and_splits_the_answer(self):
        session = CallingSession()
        body = a_client(session).post(
            "/api/call", json={"name": "find_callers", "arguments": {"symbol": "A.b", "depth": 2}}).json()
        self.assertEqual(session.called, ("find_callers", {"symbol": "A.b", "depth": 2}))
        self.assertTrue(body["ok"])
        self.assertEqual(body["note"], NOTE)
        self.assertEqual(body["payload"], PAYLOAD)
        self.assertEqual(body["kind"], "code")

    def test_a_tool_refusal_comes_back_as_a_result_not_a_failure(self):
        session = CallingSession(reply=result("check doc_type", is_error=True))
        body = a_client(session).post("/api/call", json={"name": "get_document_context"}).json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["is_error"])
        self.assertIn("check doc_type", body["text"])

    def test_a_dead_session_is_reported(self):
        session = CallingSession(fails="The MCP server is not running.")
        body = a_client(session).post("/api/call", json={"name": "find_callers"}).json()
        self.assertFalse(body["ok"])
        self.assertIn("not running", body["error"])

    def test_a_nameless_call_is_refused_by_validation(self):
        self.assertEqual(a_client(CallingSession()).post("/api/call", json={"arguments": {}}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
