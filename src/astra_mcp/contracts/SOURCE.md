# Vendored contract

`code-adapter.openapi.yaml` is copied, unchanged, from the code plane.

- Source: `Astra-RAG` branch `master`, path `contracts/code-adapter.openapi.yaml`
- Commit: `5dbce67c56ee68731be64bb215db6c2e65508b89` (2026-10-28)
- Copied: 2026-10-31

The code tools are built from this file at import, so it is the single definition of their arguments and
limits. Only the contract is vendored, not the adapter: it is a separate service under its own team.

**When the code plane changes its contract, replace this file and update the commit above.**
`tests/mcp/test_code_contract.py` pins the parts we rely on, so a change that affects the tools fails there
with the field named, rather than turning into a 422 at runtime.
