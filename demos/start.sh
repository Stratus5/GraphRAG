#!/usr/bin/env bash
# Start the GraphRAG demo: stores (Neo4j + Weaviate) then the containerized demo app.
#   ./demos/start.sh   ->  http://127.0.0.1:8800
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

if [ ! -f .env ]; then
  echo "WARN: no .env — Live mode needs OPENAI_BASE_URL/OPENAI_API_KEY; Curated still works." >&2
fi

echo "==> Bringing up stores (Neo4j + Weaviate) ..."
docker compose up -d

echo "==> Building + starting the demo app ..."
docker compose -f demos/docker-compose.yml up -d --build

echo
echo "  GraphRAG demo -> http://127.0.0.1:8800"
echo "  logs: docker logs -f graphrag-demo"
