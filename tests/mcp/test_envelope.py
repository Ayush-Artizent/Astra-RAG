"""The signer must produce what `code-adapter/src/envelope.ts` verifies."""
import base64
import hmac
import json
import unittest
from hashlib import sha256

from astra_mcp.envelope import LIFETIME_SECONDS, sign

from .fake_plane import a_config


def decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.config = a_config()
        self.header = sign(self.config, ["query"], "req-1", now=1_700_000_000)

    def test_shape_is_body_dot_signature_without_padding(self):
        body, signature = self.header.split(".")
        self.assertNotIn("=", self.header)
        self.assertEqual(len(self.header.split(".")), 2)
        self.assertTrue(body and signature)

    def test_signature_is_hmac_sha256_over_the_body_part(self):
        body, signature = self.header.split(".")
        expected = hmac.new(self.config.envelope_key.encode(), body.encode("ascii"), sha256).digest()
        self.assertEqual(decode(signature), expected)

    def test_payload_carries_the_bound_project_and_the_asked_scopes(self):
        payload = json.loads(decode(self.header.split(".")[0]))
        self.assertEqual(payload["org_id"], "nous")
        self.assertEqual(payload["project_id"], "devx-123")
        self.assertEqual(payload["scopes"], ["query"])
        self.assertEqual(payload["request_id"], "req-1")

    def test_lifetime_stays_inside_the_adapters_five_minute_maximum(self):
        payload = json.loads(decode(self.header.split(".")[0]))
        self.assertEqual(payload["exp"] - payload["iat"], LIFETIME_SECONDS)
        self.assertLessEqual(payload["exp"] - payload["iat"], 300)

    def test_a_different_key_gives_a_different_signature(self):
        other = sign(a_config(envelope_key="z" * 16), ["query"], "req-1", now=1_700_000_000)
        self.assertNotEqual(other.split(".")[1], self.header.split(".")[1])
        self.assertEqual(other.split(".")[0], self.header.split(".")[0])


if __name__ == "__main__":
    unittest.main()
