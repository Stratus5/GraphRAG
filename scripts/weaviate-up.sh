#!/usr/bin/env bash
# Start Weaviate via plain podman (fallback when `podman compose` is unavailable).
# Joins the shared graphrag-net network so the demo container can reach it by name.
set -euo pipefail

NET=graphrag-net
podman network exists "$NET" || podman network create "$NET"

if podman container exists graphrag-weaviate; then
  podman start graphrag-weaviate
else
  podman run -d --name graphrag-weaviate --network "$NET" \
    -p 127.0.0.1:8080:8080 -p 127.0.0.1:50051:50051 \
    -e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true \
    -e PERSISTENCE_DATA_PATH=/var/lib/weaviate \
    -e DEFAULT_VECTORIZER_MODULE=none \
    -e ENABLE_MODULES= \
    -e CLUSTER_HOSTNAME=node1 \
    -v weaviate_data:/var/lib/weaviate \
    cr.weaviate.io/semitechnologies/weaviate:1.38.1
fi

echo "==> Waiting for Weaviate readiness ..."
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8080/v1/.well-known/ready >/dev/null; then
    echo "==> Weaviate is ready."; exit 0
  fi
  sleep 1
done
echo "ERROR: Weaviate did not become ready in time." >&2
exit 1
