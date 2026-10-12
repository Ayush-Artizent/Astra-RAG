"""Export rag-api's OpenAPI spec. The TypeScript SDK is generated from this file (§12)."""

import json
import sys
from pathlib import Path

from rag_api.main import create_app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
out.write_text(json.dumps(create_app().openapi(), indent=2), encoding="utf-8")
print(f"wrote {out}")
