"""The mTLS service path must stay graph-only: it must never import the vector layer.
Static source check (not sys.modules) so unrelated tests importing weaviate can't
mask a real violation."""
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent / "graphrag"
SERVICE_PATH_FILES = [
    _ROOT / "retrieval" / "service.py",
    _ROOT / "api.py",
    _ROOT / "mcp_server.py",
]
FORBIDDEN = ("import weaviate", "from weaviate", "vectorstore")


@pytest.mark.parametrize("path", SERVICE_PATH_FILES, ids=lambda p: p.name)
def test_service_path_does_not_import_vector_layer(path):
    src = path.read_text()
    for needle in FORBIDDEN:
        assert needle not in src, f"{path.name} must not reference '{needle}' (graph-only invariant)"
