import logging
import unittest

from astra_rag.services.sources.credentials import PatCredential

TOKEN = "ghp_supersecret123"


class PatCredentialTests(unittest.TestCase):
    def test_secret_returns_the_token(self):
        self.assertEqual(PatCredential(TOKEN).secret(), TOKEN)

    def test_token_is_never_in_text_forms(self):
        cred = PatCredential(TOKEN)
        for text in (repr(cred), str(cred), f"{cred}", f"{cred!r}", "%s %r" % (cred, [cred]), repr({"c": cred})):
            self.assertNotIn(TOKEN, text)

    def test_token_is_not_in_logs(self):
        with self.assertLogs("astra-test", level="INFO") as logs:
            logging.getLogger("astra-test").info("using %s", PatCredential(TOKEN))
        self.assertNotIn(TOKEN, "\n".join(logs.output))

    def test_no_attribute_dict_to_dump(self):
        self.assertFalse(hasattr(PatCredential(TOKEN), "__dict__"))


if __name__ == "__main__":
    unittest.main()
