import os
import tempfile

# Safety net: no test may touch the real data/astra.db. Suites that use the registry also call
# tests.helpers.use_temp_registry() for a fresh database each.
os.environ["ASTRA_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="astra-tests-"), "astra.db")
