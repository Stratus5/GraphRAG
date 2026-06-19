"""End-to-end ingest -> retrieve through the real pipeline, with extraction
stubbed (the LLM is the platform gateway's job, not what we're testing here).
Exercises the full service write path including the reconcile-by-source loop.
Loopback Neo4j; no gateway key.
"""

import pytest
from langchain_community.graphs.graph_document import GraphDocument, Node, Relationship
from langchain_core.documents import Document

from graphrag.config import load_config
from graphrag.ingestion.pipeline import ingest_chunks
from graphrag.ingestion.writer import get_graph
from graphrag.retrieval.service import retrieve
from tests.conftest import reset_schema


def _fake_extract(_transformer, docs, on_progress=None):
    """Stand in for LLM extraction: Acme Corp -ACQUIRED-> <chunk text>, per chunk."""
    gdocs = []
    for d in docs:
        acme = Node(id="Acme Corp", type="Company")
        target = Node(id=d.page_content, type="Company")
        gdocs.append(GraphDocument(
            nodes=[acme, target],
            relationships=[Relationship(source=acme, target=target, type="ACQUIRED")],
            source=Document(page_content=d.page_content,
                            metadata={"id": d.metadata["id"], "source": d.metadata["source"]}),
        ))
    return gdocs, 0


@pytest.fixture
def cfg(neo4j_available, monkeypatch):
    cfg = load_config("config.yaml")
    g = get_graph(cfg)
    g.query("MATCH (n) DETACH DELETE n")
    reset_schema(g)
    g.close()
    # Stub the LLM-bound bits so the real write path runs offline.
    monkeypatch.setattr("graphrag.ingestion.pipeline.get_chat_model", lambda c: None)
    monkeypatch.setattr("graphrag.ingestion.pipeline.build_transformer", lambda **k: None)
    monkeypatch.setattr("graphrag.ingestion.pipeline.extract_graph", _fake_extract)
    return cfg


def test_ingest_chunks_then_retrieve(cfg):
    ingest_chunks(cfg, "A", [{"chunk_id": "c1", "text": "Beta Labs", "source": "doc.txt"}])
    facts = retrieve(get_graph(cfg), "A", ["c1"], hops=2)
    assert "Beta Labs" in {f["object"] for f in facts}


def test_reingest_via_pipeline_reconciles_by_source(cfg):
    ingest_chunks(cfg, "A", [{"chunk_id": "c1", "text": "Old Co", "source": "doc.txt"}])
    # Edit churns chunk_id; same source -> the pipeline's delete-before-write must
    # drop the stale chunk + orphaned "Old Co".
    ingest_chunks(cfg, "A", [{"chunk_id": "c2", "text": "New Co", "source": "doc.txt"}])

    g = get_graph(cfg)
    ids = {e["id"] for e in g.query("MATCH (e:__Entity__ {tenant:'A'}) RETURN e.id AS id")}
    assert "New Co" in ids and "Old Co" not in ids
    assert g.query("MATCH (c:Chunk {tenant:'A', chunk_id:'c1'}) RETURN count(c) AS n")[0]["n"] == 0
    assert "New Co" in {f["object"] for f in retrieve(g, "A", ["c2"], hops=2)}
