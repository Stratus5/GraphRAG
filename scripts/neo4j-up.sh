#!/usr/bin/env bash
# Start the GraphRAG Neo4j container with plain podman.
# Use this when `podman compose` is unavailable (e.g. broken nested podman in a toolbox).
# The compose file (docker-compose.yml) describes the same container; this is an
# equivalent fallback that does not depend on podman-compose.
set -euo pipefail

podman run -d --name graphrag-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc"]' \
  -v neo4j_data:/data \
  docker.io/library/neo4j:5.23

echo "Waiting for Neo4j to accept connections..."
for _ in $(seq 1 30); do
  if curl -s -o /dev/null http://localhost:7474; then
    echo "Neo4j up at http://localhost:7474 (bolt://localhost:7687)"
    exit 0
  fi
  sleep 2
done
echo "Neo4j did not become ready in time; check 'podman logs graphrag-neo4j'." >&2
exit 1
