import unittest

from astra_mcp.config import DEFAULT_CODE_URL, DEFAULT_DOC_URL, DEFAULT_TIMEOUT_MS, ConfigError, load

KEY = "k" * 16


def env(**overrides) -> dict:
    base = {"ASTRA_ORG_ID": "nous", "ASTRA_PROJECT_ID": "devx-123", "ASTRA_ENVELOPE_KEY": KEY}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


class ConfigTests(unittest.TestCase):
    def test_minimal_environment_uses_defaults(self):
        config = load(env())
        self.assertEqual(config.org_id, "nous")
        self.assertEqual(config.project_id, "devx-123")
        self.assertEqual(config.doc_url, DEFAULT_DOC_URL)
        self.assertEqual(config.code_url, DEFAULT_CODE_URL)
        self.assertEqual(config.timeout_ms, DEFAULT_TIMEOUT_MS)
        self.assertEqual(config.timeout_seconds, DEFAULT_TIMEOUT_MS / 1000)

    def test_missing_required_names_the_variable(self):
        for name in ("ASTRA_ORG_ID", "ASTRA_PROJECT_ID", "ASTRA_ENVELOPE_KEY"):
            with self.subTest(name=name):
                with self.assertRaises(ConfigError) as caught:
                    load(env(**{name: None}))
                self.assertIn(name, str(caught.exception))

    def test_blank_is_the_same_as_missing(self):
        with self.assertRaises(ConfigError):
            load(env(ASTRA_ORG_ID="   "))

    def test_short_envelope_key_is_refused_without_echoing_it(self):
        with self.assertRaises(ConfigError) as caught:
            load(env(ASTRA_ENVELOPE_KEY="too-short"))
        message = str(caught.exception)
        self.assertIn("16", message)
        self.assertNotIn("too-short", message)

    def test_id_must_satisfy_the_stricter_code_plane_pattern(self):
        # The doc plane would accept all of these; the code plane turns them into directory names.
        for bad in ("has.dot", "-leading-dash", "_leading_underscore", "has space", "a" * 65, "has/slash"):
            with self.subTest(value=bad):
                with self.assertRaises(ConfigError):
                    load(env(ASTRA_PROJECT_ID=bad))

    def test_ids_that_work_on_both_planes_are_accepted(self):
        for good in ("a", "nous", "devx-123", "Devx_123", "9lives", "a" * 64):
            with self.subTest(value=good):
                self.assertEqual(load(env(ASTRA_PROJECT_ID=good)).project_id, good)

    def test_urls_need_a_scheme_and_lose_a_trailing_slash(self):
        with self.assertRaises(ConfigError):
            load(env(ASTRA_DOC_URL="127.0.0.1:5000"))
        self.assertEqual(load(env(ASTRA_DOC_URL="http://host:5000/")).doc_url, "http://host:5000")
        self.assertEqual(load(env(ASTRA_CODE_URL="https://host/")).code_url, "https://host")

    def test_timeout_must_be_a_positive_whole_number(self):
        for bad in ("0", "-1", "1.5", "soon"):
            with self.subTest(value=bad):
                with self.assertRaises(ConfigError):
                    load(env(ASTRA_MCP_TIMEOUT_MS=bad))
        self.assertEqual(load(env(ASTRA_MCP_TIMEOUT_MS="2000")).timeout_ms, 2000)


if __name__ == "__main__":
    unittest.main()
