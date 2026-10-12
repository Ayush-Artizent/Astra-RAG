# @astra/rag-sdk (TypeScript) — planned

Per design doc §12 / §13 the TS SDK is **generated from the OpenAPI spec** and may trail the
Python SDK by a week or two. Nothing here is hand-written retrieval logic.

Plan (platform pod):

```bash
uv run poe openapi                          # writes openapi.json from rag-api
npx openapi-typescript openapi.json -o src/schema.d.ts
# thin client over fetch + openapi-fetch, same tool names as REST/MCP/Python SDK
```

CI will regenerate and diff on every API change so the SDK can never drift from the server.
