from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(neo4j_available):
    from demos import server
    return TestClient(server.app)


def test_ask_curated_mode_unchanged(client):
    r = client.post("/api/ask", json={"id": "FOUNDER_CO", "mode": "curated"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "curated"
    assert "facts" in body and "answer" in body


def test_ask_live_mode_runs_vector_then_retrieve(client):
    hits = [{"chunk_id": "ada_whitfield", "text": "t", "source": "s", "score": 0.9}]
    facts = [{"subject": "Ada Whitfield", "predicate": "FOUNDED", "object": "Helix Robotics"}]
    with patch("demos.server.vectorstore") as vs, \
         patch("demos.server.service_retrieve", return_value=facts) as ret, \
         patch("demos.server.get_embeddings"):
        vs.search.return_value = hits
        r = client.post("/api/ask", json={"id": "FOUNDER_CO", "mode": "live"})
    body = r.json()
    assert body["mode"] == "live"
    assert body["vector_hits"] == hits
    assert body["facts"] == facts
    ret.assert_called_once()
