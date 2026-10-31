import json
import unittest

import httpx

from astra_mcp.code_client import CodeClient
from astra_mcp.envelope import HEADER
from astra_mcp.errors import PlaneError
from astra_mcp.tools_code import TOOLS, builder

from .fake_plane import QUERY_RESULT, FakeCodePlane, a_config


class CodeClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plane = FakeCodePlane()
        self.client = CodeClient(a_config(), self.plane.client())

    async def test_every_call_carries_a_signed_envelope_and_a_request_id(self):
        await self.client.query({"mode": "lookup", "keywords": ["token"]})
        request = self.plane.requests[-1]
        self.assertRegex(request.headers[HEADER.lower()], r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self.assertTrue(request.headers["x-request-id"])

    async def test_the_envelope_is_fresh_for_each_call(self):
        await self.client.status()
        first = self.plane.envelope_header()
        await self.client.status()
        self.assertNotEqual(first, self.plane.envelope_header())

    async def test_a_not_ready_plane_is_an_answer_not_a_failure(self):
        self.plane.query_result = {**QUERY_RESULT, "plane_status": "not_ready", "results": []}
        result = await self.client.query({"mode": "lookup", "keywords": ["x"]})
        self.assertEqual(result["plane_status"], "not_ready")

    async def test_a_problem_json_refusal_becomes_a_safe_message(self):
        self.plane.problem = (422, {"type": "about:blank", "title": "Invalid request", "status": 422,
                                    "detail": "symbols: must be an array of strings",
                                    "error_code": "invalid_field", "field": "symbols"})
        with self.assertRaises(PlaneError) as caught:
            await self.client.query({"mode": "lookup"})
        self.assertIn("symbols: must be an array of strings", str(caught.exception))
        self.assertIn("invalid_field", str(caught.exception))

    async def test_an_unreachable_plane_does_not_leak_the_url(self):
        self.plane.raises = httpx.ConnectError("refused by http://127.0.0.1:8091")
        with self.assertRaises(PlaneError) as caught:
            await self.client.status()
        self.assertIn("ConnectError", str(caught.exception))
        self.assertNotIn("8091", str(caught.exception))


class ToolBodyTests(unittest.TestCase):
    def test_a_single_symbol_becomes_the_arrays_the_adapter_wants(self):
        body = builder("find_callers")({"symbol": "TokenService.issue", "depth": 2})
        self.assertEqual(body, {"mode": "callers", "depth": 2, "symbols": ["TokenService.issue"]})

    def test_impact_and_callers_differ_only_by_mode(self):
        args = {"symbol": "A.b"}
        self.assertEqual(builder("analyze_impact")(args)["mode"], "impact")
        self.assertEqual(builder("find_callers")(args)["mode"], "callers")

    def test_flow_passes_the_symbols_through_in_order(self):
        body = builder("trace_flow")({"symbols": ["A.b", "C.d"]})
        self.assertEqual(body, {"mode": "flow", "symbols": ["A.b", "C.d"]})

    def test_unknown_arguments_are_dropped_because_the_adapter_refuses_them(self):
        body = builder("find_symbol")({"keywords": ["token"], "sneaky": 1, "mode": "impact"})
        self.assertEqual(body, {"mode": "lookup", "keywords": ["token"]})

    def test_status_has_no_body_builder(self):
        self.assertIsNone(builder("code_index_status"))

    def test_arity_rules_are_in_the_schemas_not_left_to_the_adapter(self):
        self.assertEqual(TOOLS["find_callers"]["schema"]["required"], ["symbol"])
        self.assertEqual(TOOLS["analyze_impact"]["schema"]["required"], ["symbol"])
        self.assertEqual(TOOLS["trace_flow"]["schema"]["properties"]["symbols"]["minItems"], 2)
        self.assertEqual(TOOLS["find_symbol"]["schema"]["anyOf"],
                         [{"required": ["symbols"]}, {"required": ["keywords"]}])


if __name__ == "__main__":
    unittest.main()
