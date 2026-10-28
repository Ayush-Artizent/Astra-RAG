import unittest

from astra_rag.config import SUPPORTED_HOST_KINDS
from astra_rag.services.sources import PatCredential, adapter_for, parse_repo_url
from astra_rag.services.sources.azure_devops import AzureDevOpsAdapter
from astra_rag.services.sources.github import GitHubAdapter
from astra_rag.services.sources.registry import ADAPTERS


class RegistryTests(unittest.TestCase):
    def test_every_supported_host_kind_has_an_adapter(self):
        # Adding a host means touching both config and the registry; this catches one without the other.
        self.assertEqual(set(ADAPTERS), set(SUPPORTED_HOST_KINDS))

    def test_github_and_enterprise_use_the_github_adapter(self):
        for url in ("https://github.com/acme/golden", "https://git.acme.com/acme/golden"):
            adapter = adapter_for(parse_repo_url(url), PatCredential("t"))
            self.assertIsInstance(adapter, GitHubAdapter)
            self.assertEqual(adapter.ref, parse_repo_url(url))

    def test_azure_devops_uses_its_own_adapter(self):
        ref = parse_repo_url("https://dev.azure.com/acme/proj/_git/golden")
        self.assertIsInstance(adapter_for(ref, PatCredential("t")), AzureDevOpsAdapter)


if __name__ == "__main__":
    unittest.main()
