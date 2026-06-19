#!/usr/bin/env bash
# Print relations from the GraphRAG Neo4j graph.
# Runs a Cypher query via cypher-shell inside the running container.
#
# Usage:
#   ./scripts/show-relations.sh              # default query, LIMIT 25
#   LIMIT=100 ./scripts/show-relations.sh    # override row limit
#   ./scripts/show-relations.sh "MATCH (n) RETURN n LIMIT 5"   # custom query
set -euo pipefail

CONTAINER="${CONTAINER:-graphrag-neo4j}"

# Load Neo4j credentials from .env if present, else fall back to defaults.
ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
USER="${NEO4J_USERNAME:-neo4j}"
PASS="${NEO4J_PASSWORD:-password123}"

LIMIT="${LIMIT:-25}"
DEFAULT_QUERY="MATCH (a)-[r]->(b) RETURN labels(a) AS from, coalesce(a.id,a.name,a.text,'') AS from_val, type(r) AS rel, labels(b) AS to, coalesce(b.id,b.name,b.text,'') AS to_val LIMIT ${LIMIT};"
QUERY="${1:-$DEFAULT_QUERY}"

podman exec "$CONTAINER" cypher-shell -u "$USER" -p "$PASS" "$QUERY"
