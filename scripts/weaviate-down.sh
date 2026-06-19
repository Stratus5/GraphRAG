#!/usr/bin/env bash
set -euo pipefail
podman stop graphrag-weaviate 2>/dev/null || true
