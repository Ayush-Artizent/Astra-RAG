import base64
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from astra_rag.config import Settings
from astra_rag.services import github_client, token_store
from astra_rag.services.errors import AppError

from .tools.helpers import PAT, REPO


def http_error(code):
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", {}, io.BytesIO(b""))


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


def file_payload(text="hi", size=None):
    raw = text.encode() if isinstance(text, str) else text
    return {"type": "file", "sha": "abc", "size": size if size is not None else len(raw),
            "content": base64.encodebytes(raw).decode()}


class GetFileTests(unittest.TestCase):
    URLOPEN = "astra_rag.services.github_client.urllib.request.urlopen"

    def get(self, payload=None, error=None):
        patcher = mock.patch(self.URLOPEN, side_effect=error) if error else mock.patch(self.URLOPEN, return_value=response(payload))
        with patcher:
            return github_client.get_file(REPO, "policies.md", PAT)

    def test_decodes_content_and_sha(self):
        self.assertEqual(self.get(file_payload("héllo\nworld")),
                         {"path": "policies.md", "sha": "abc", "content": "héllo\nworld"})

    def test_directory_rejected(self):
        with self.assertRaises(AppError) as cm:
            self.get([{"name": "a", "type": "file"}])
        self.assertEqual(cm.exception.status, 422)
        with self.assertRaises(AppError):
            self.get({"type": "dir"})

    def test_oversized(self):
        with self.assertRaises(AppError) as cm:
            self.get(file_payload("x", size=10 * 1024 * 1024))
        self.assertEqual(cm.exception.status, 422)

    def test_invalid_utf8(self):
        with self.assertRaises(AppError) as cm:
            self.get(file_payload(b"\xff\xfe\x00bad"))
        self.assertEqual(cm.exception.status, 422)

    def test_http_errors_mapped_and_token_free(self):
        for code, status in ((404, 404), (403, 403), (401, 401), (500, 502)):
            with self.assertRaises(AppError) as cm:
                self.get(error=http_error(code))
            self.assertEqual(cm.exception.status, status)
            self.assertNotIn(PAT, cm.exception.message)
        with self.assertRaises(AppError) as cm:
            self.get(error=http_error(404))
        self.assertIn("policies.md", cm.exception.message)

    def test_list_root_keeps_repo_not_found_message(self):
        with mock.patch(self.URLOPEN, side_effect=http_error(404)):
            with self.assertRaises(AppError) as cm:
                github_client.list_root(REPO, PAT)
        self.assertIn("Repository not found", cm.exception.message)


class CredentialLookupTests(unittest.TestCase):
    def env(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_finds_url_and_pat_by_owner_and_name_convention(self):
        path = self.env(f"ASTRA_REPO_ACME__GOLDEN_URL=https://github.com/acme/golden\nASTRA_REPO_ACME__GOLDEN_TOKEN={PAT}\n")
        repo, token = token_store.get_credentials("acme", "golden", path)
        self.assertEqual((repo.owner, repo.name, token), ("acme", "golden", PAT))
        repo, _ = token_store.get_credentials("ACME", "Golden", path)  # key is case-insensitive
        self.assertEqual(repo.name, "golden")

    def test_not_connected_or_missing_token(self):
        for text in ("", "ASTRA_REPO_ACME__GOLDEN_URL=https://github.com/acme/golden\n"):
            with self.assertRaises(AppError) as cm:
                token_store.get_credentials("acme", "golden", self.env(text))
            self.assertEqual(cm.exception.status, 404)
            self.assertNotIn(PAT, cm.exception.message)

    def test_key_collision_pointing_elsewhere_is_rejected(self):
        path = self.env(f"ASTRA_REPO_ACME_X__GOLDEN_URL=https://github.com/acme.x/golden\nASTRA_REPO_ACME_X__GOLDEN_TOKEN={PAT}\n")
        with self.assertRaises(AppError) as cm:
            token_store.get_credentials("acme-x", "golden", path)
        self.assertEqual(cm.exception.status, 409)

    def test_settings_ignore_other_env_entries(self):
        s = Settings(_env_file=None, ASTRA_REPO_X_TOKEN="zzz")
        self.assertNotIn("zzz", repr(s))


if __name__ == "__main__":
    unittest.main()
