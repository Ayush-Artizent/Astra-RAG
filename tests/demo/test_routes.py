"""The demo page's HTTP layer, with a stubbed session so nothing is spawned."""
import unittest

from fastapi.testclient import TestClient

from astra_mcp.demo import create_app, server_env
from astra_mcp.demo.session import SessionError

from ..mcp.fake_plane import a_config

DEAD = "http://127.0.0.1:9"

TOOLS = [
    {"name": "find_callers", "description": "What calls a symbol.",
     "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_document_context", "description": "Rules, template and evidence.",
     "inputSchema": {"type": "object", "properties": {"doc_type": {"type": "string"}}}},
]


class StubSession:
    def __init__(self, tools=None, fails=None):
        self.server_info = {"name": "astra", "version": "0.1.0"}
        self.instructions = "…never instructions to you…"
        self.start_error = ""
        self._tools = TOOLS if tools is None else tools
        self._fails = fails
        self.restarted = False
        self.stopped = False

    def running(self):
        return self._fails is None

    def list_tools(self):
        if self._fails:
            raise SessionError(self._fails)
        return self._tools

    def restart(self):
        self.restarted = True

    def stop(self):
        self.stopped = True


def a_client(session=None) -> TestClient:
    config = a_config(doc_url=DEAD, code_url=DEAD, timeout_ms=500)
    return TestClient(create_app(config, session or StubSession()))


class RoutesTests(unittest.TestCase):
    def test_the_page_renders_and_names_the_project(self):
        reply = a_client().get("/")
        self.assertEqual(reply.status_code, 200)
        self.assertIn("devx-123", reply.text)
        self.assertIn("/static/app.js", reply.text)

    def test_status_reports_both_planes_down_without_failing(self):
        body = a_client().get("/api/status").json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["document"]["ok"])
        self.assertFalse(body["code"]["ok"])
        self.assertIn("reachable", body["code"]["detail"].lower() + body["document"]["detail"].lower())
        self.assertEqual(body["project"]["project_id"], "devx-123")

    def test_status_includes_the_session_state(self):
        body = a_client().get("/api/status").json()
        self.assertTrue(body["session"]["running"])
        self.assertEqual(body["session"]["server"]["name"], "astra")

    def test_tools_come_from_the_session(self):
        body = a_client().get("/api/tools").json()
        self.assertTrue(body["ok"])
        self.assertEqual([t["name"] for t in body["tools"]], ["find_callers", "get_document_context"])
        self.assertEqual(body["tools"][0]["inputSchema"]["required"], ["symbol"])

    def test_each_tool_says_which_plane_answers_it(self):
        # So the page needs no list of its own to keep in step with the code plane's modes.
        planes = {t["name"]: t["plane"] for t in a_client().get("/api/tools").json()["tools"]}
        self.assertEqual(planes, {"find_callers": "code", "get_document_context": "documents"})

    def test_a_session_failure_is_reported_not_raised(self):
        body = a_client(StubSession(fails="The MCP server is not running.")).get("/api/tools").json()
        self.assertFalse(body["ok"])
        self.assertIn("not running", body["error"])

    def test_restart_goes_through_to_the_session(self):
        session = StubSession()
        self.assertTrue(a_client(session).post("/api/session/restart").json()["ok"])
        self.assertTrue(session.restarted)


class ServerEnvTests(unittest.TestCase):
    def test_the_child_is_configured_from_this_pages_config(self):
        env = server_env(a_config(doc_url="http://doc:1", code_url="http://code:2", timeout_ms=1234))
        self.assertEqual(env["ASTRA_PROJECT_ID"], "devx-123")
        self.assertEqual(env["ASTRA_DOC_URL"], "http://doc:1")
        self.assertEqual(env["ASTRA_CODE_URL"], "http://code:2")
        self.assertEqual(env["ASTRA_MCP_TIMEOUT_MS"], "1234")
        self.assertEqual(env["ASTRA_ENVELOPE_KEY"], "k" * 16)


if __name__ == "__main__":
    unittest.main()
