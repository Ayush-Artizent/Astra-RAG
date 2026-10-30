import os
import tempfile

# Safety net: no test may touch the real data/astra.db. Suites that use the registry also call
# tests.helpers.use_temp_registry() for a fresh database each.
os.environ["ASTRA_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="astra-tests-"), "astra.db")
# No nightly scheduler, catch-up or startup index recovery in tests (they would reach for a real Qdrant).
os.environ["ASTRA_SYNC_SCHEDULER"] = "0"
# No model download or load at app startup in tests (they use fake embedders and rerankers).
os.environ["ASTRA_MODELS_PREFETCH"] = "0"
