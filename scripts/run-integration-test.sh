#!/usr/bin/env bash
# Run the GraphRAG end-to-end integration test.
#
# Requirements:
#   1. A live Neo4j (this script starts it via scripts/neo4j-up.sh if not already up).
#   2. OPENAI_API_KEY exported in your shell (NOT just in .env — the test's skipif
#      checks os.environ at collection time, before load_dotenv() runs).
#
# Usage:
#   export OPENAI_API_KEY=sk-...
#   ./scripts/run-integration-test.sh
#
# Optional env overrides (defaults match docker-compose.yml / scripts/neo4j-up.sh):
#   NEO4J_URI (bolt://localhost:7687)  NEO4J_USERNAME (neo4j)  NEO4J_PASSWORD (password123)
set -euo pipefail

cd "$(dirname "$0")/.."   # project root

PY=.venv/bin/python
export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
export NEO4J_USERNAME="${NEO4J_USERNAME:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password123}"

# --- Preconditions ---------------------------------------------------------
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is not exported." >&2
  echo "       Run: export OPENAI_API_KEY=sk-...   then re-run this script." >&2
  echo "       (Putting it only in .env will cause the test to SKIP.)" >&2
  exit 1
fi

if [[ ! -x "$PY" ]]; then
  echo "ERROR: $PY not found. Create the venv and install: pip install -e \".[openai,dev]\"" >&2
  exit 1
fi

# --- Ensure Neo4j is reachable --------------------------------------------
echo "==> Checking Neo4j at $NEO4J_URI ..."
if ! curl -s -o /dev/null http://localhost:7474; then
  echo "==> Neo4j not reachable; starting it via scripts/neo4j-up.sh"
  ./scripts/neo4j-up.sh
else
  echo "==> Neo4j is up."
fi

# --- Run the integration test ---------------------------------------------
echo "==> Running integration test ..."
"$PY" -m pytest tests/test_integration.py -v

# --- Prove graph expansion actually populated (GraphRAG, not just vector RAG) ----
echo "==> Verifying chunk -> entity links exist in the graph ..."
"$PY" - <<'PYEOF'
import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
)
with driver.session() as s:
    mentions = s.run("MATCH (:Chunk)-[:MENTIONS]->() RETURN count(*) AS n").single()["n"]
    entities = s.run("MATCH (e:__Entity__) RETURN count(e) AS n").single()["n"]
driver.close()

print(f"    Chunk-[:MENTIONS]->entity edges: {mentions}")
print(f"    Extracted entities:             {entities}")
if mentions == 0:
    raise SystemExit("FAIL: graph expansion path is empty (no Chunk->entity links).")
print("    OK: graph expansion path is populated.")
PYEOF

echo "==> Integration test complete."
