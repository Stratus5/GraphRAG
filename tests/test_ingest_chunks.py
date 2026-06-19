from graphrag.ingestion.pipeline import _documents_from_chunks
from graphrag.ingestion.writer import write_chunks


def test_documents_from_chunks_sets_id_and_source():
    docs = _documents_from_chunks([
        {"chunk_id": "abc", "text": "Acme acquired Beta.", "source": "acme.txt"},
    ])
    assert len(docs) == 1
    d = docs[0]
    assert d.page_content == "Acme acquired Beta."
    # metadata["id"]=chunk_id is mandatory for link_chunks_to_entities to find MENTIONS.
    assert d.metadata["id"] == "abc"
    assert d.metadata["chunk_id"] == "abc"
    assert d.metadata["source"] == "acme.txt"


class FakeGraph:
    def __init__(self):
        self.calls = []

    def query(self, q, params=None):
        self.calls.append((q, params))
        return []


def test_write_chunks_stores_no_embeddings():
    docs = _documents_from_chunks([
        {"chunk_id": "abc", "text": "Acme acquired Beta.", "source": "acme.txt"},
    ])
    g = FakeGraph()
    write_chunks(g, docs, tenant="A")
    # exactly one write, no VECTOR_INDEX creation
    assert len(g.calls) == 1
    cypher, params = g.calls[0]
    assert "embedding" not in cypher.lower()
    assert "vector index" not in cypher.lower()
    assert params["tenant"] == "A"
    row = params["rows"][0]
    assert set(row) == {"source", "chunk_id", "text"}
