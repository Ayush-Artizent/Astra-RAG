"""Pins the parts of the vendored contract the code tools are built from.

The code plane owns `contracts/code-adapter.openapi.yaml`. When their team changes it and refreshes
our copy, a change that affects the tools should fail here, naming the field, instead of becoming a
422 at runtime. See `src/astra_mcp/contracts/SOURCE.md`.
"""
import unittest

from astra_mcp.tools_code import CONTRACT, SHARED, TOOLS, request_properties


class ContractTests(unittest.TestCase):
    def test_the_contract_is_vendored_with_the_package(self):
        self.assertTrue(CONTRACT.is_file(), f"missing vendored contract at {CONTRACT}")

    def test_the_modes_the_tools_cover_still_exist(self):
        modes = request_properties()["mode"]["enum"]
        self.assertEqual(set(modes), {"lookup", "flow", "callers", "impact"})

    def test_every_argument_the_tools_use_is_still_in_the_contract(self):
        defined = set(request_properties())
        used = {"symbols", "keywords", *SHARED, "depth"}
        self.assertEqual(used - defined, set(), "the contract no longer defines these")

    def test_the_limits_the_schemas_inherit_are_unchanged(self):
        props = request_properties()
        self.assertEqual(props["depth"]["minimum"], 1)
        self.assertEqual(props["depth"]["maximum"], 5)
        self.assertEqual(props["limit"]["minimum"], 1)
        self.assertEqual(props["limit"]["maximum"], 50)
        self.assertEqual(props["symbols"]["maxItems"], 20)
        self.assertEqual(props["symbols"]["items"]["maxLength"], 300)
        self.assertEqual(props["max_code_chars"]["maximum"], 20000)

    def test_schemas_inherit_those_limits_rather_than_restating_them(self):
        symbol = TOOLS["find_callers"]["schema"]["properties"]["symbol"]
        self.assertEqual(symbol["maxLength"], request_properties()["symbols"]["items"]["maxLength"])
        depth = TOOLS["analyze_impact"]["schema"]["properties"]["depth"]
        self.assertEqual(depth["maximum"], request_properties()["depth"]["maximum"])

    def test_the_server_never_offers_arguments_it_should_own(self):
        # `mode` is set by the tool; `fallback_origin` describes how the caller found its terms.
        for name, tool in TOOLS.items():
            with self.subTest(tool=name):
                self.assertNotIn("mode", tool["schema"]["properties"])
                self.assertNotIn("fallback_origin", tool["schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
