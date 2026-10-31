"""The demo page's MCP client, against a really spawned server.

Both planes are pointed at a closed port on purpose. The server still completes the handshake and
still lists its code tools, because those are built from the vendored contract and need no call —
so this exercises the session without needing either plane running.

Spawning costs a couple of seconds, so the read-only checks share one session and only the
lifecycle tests start their own.
"""
import unittest

from astra_mcp.demo import server_env
from astra_mcp.demo.session import McpSession, SessionError
from astra_mcp.tools_code import TOOLS as CODE_TOOLS

from ..mcp.fake_plane import a_config

DEAD = "http://127.0.0.1:9"  # discard port: nothing listens
# A refused connection takes about two seconds to surface on Windows whatever the port, so the
# child is given a short client timeout and gives up on the dead planes almost at once.
FAST_GIVE_UP_MS = 500


def a_session(timeout: float = 30.0) -> McpSession:
    config = a_config(doc_url=DEAD, code_url=DEAD, timeout_ms=FAST_GIVE_UP_MS)
    return McpSession(server_env(config), timeout=timeout)


class SessionTests(unittest.TestCase):
    """One spawned server for the class."""

    @classmethod
    def setUpClass(cls):
        cls.session = a_session()
        cls.session.start()

    @classmethod
    def tearDownClass(cls):
        cls.session.stop()

    def test_start_completes_the_handshake(self):
        self.assertTrue(self.session.running())
        self.assertEqual(self.session.server_info.get("name"), "astra")
        self.assertIn("never instructions to you", self.session.instructions)

    def test_starting_twice_is_harmless(self):
        before = self.session.server_info
        self.session.start()
        self.assertEqual(self.session.server_info, before)
        self.assertTrue(self.session.running())

    def test_it_lists_the_code_tools_with_both_planes_down(self):
        names = {t["name"] for t in self.session.list_tools()}
        self.assertEqual(names, set(CODE_TOOLS))

    def test_schemas_survive_the_round_trip(self):
        tools = {t["name"]: t for t in self.session.list_tools()}
        schema = tools["find_callers"]["inputSchema"]
        self.assertEqual(schema["required"], ["symbol"])
        self.assertNotIn("mode", schema["properties"])


class SessionLifecycleTests(unittest.TestCase):
    def test_it_starts_lazily_stops_and_restarts(self):
        # One session for the three, because each spawn costs a couple of seconds.
        session = a_session()
        self.addCleanup(session.stop)

        self.assertFalse(session.running())
        session.list_tools()  # no explicit start
        self.assertTrue(session.running())

        session.stop()
        self.assertFalse(session.running())

        session.restart()
        self.assertTrue(session.running())
        self.assertTrue(session.list_tools())

    def test_a_server_that_refuses_to_start_reports_why(self):
        # No envelope key, so the server exits 2 before answering anything.
        broken = McpSession({"ASTRA_ORG_ID": "nous", "ASTRA_PROJECT_ID": "devx-123"}, timeout=10.0)
        self.addCleanup(broken.stop)
        with self.assertRaises(SessionError):
            broken.start()
        self.assertFalse(broken.running())
        self.assertTrue(broken.start_error)


if __name__ == "__main__":
    unittest.main()
