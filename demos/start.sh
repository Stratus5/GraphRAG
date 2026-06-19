#!/usr/bin/env bash
# Start the GraphRAG demos (local, loopback, no gateway needed).
#   ./demos/start.sh   ->  http://127.0.0.1:8800
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

PORT="${PORT:-8800}"
VENV="${VENV:-.venv}"
PY="$VENV/bin/python"
[ -x "$PY" ] || PY="python3"

# 1. Neo4j (loopback container) must be up.
if command -v podman >/dev/null 2>&1; then
  podman start graphrag-neo4j >/dev/null 2>&1 || true
fi

# 2. Load env (Neo4j creds).
if [ -f .env ]; then set -a; . ./.env; set +a; fi

# 3. Load the demo graph (replays the frozen extraction, no LLM/gateway).
"$PY" -m demos.load

# 4. Serve the single-page app.
echo
echo "  GraphRAG demos -> http://127.0.0.1:${PORT}"
echo "  (Ctrl-C to stop)"
echo
exec "$PY" -m uvicorn demos.server:app --host 127.0.0.1 --port "$PORT"
