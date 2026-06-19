#!/usr/bin/env bash
# Stop and remove the GraphRAG Neo4j container.
# The neo4j_data named volume is preserved so graph data survives a restart.
# Pass --wipe to also delete the data volume.
set -euo pipefail

podman rm -f graphrag-neo4j 2>/dev/null || true

if [[ "${1:-}" == "--wipe" ]]; then
  podman volume rm neo4j_data 2>/dev/null || true
  echo "Removed container and wiped neo4j_data volume."
else
  echo "Removed container; neo4j_data volume preserved (use --wipe to delete it)."
fi
