from langchain_core.embeddings import Embeddings

from graphrag import vectorstore


def test_ensure_collection_is_idempotent(weaviate_available):
    client = weaviate_available
    client.collections.delete(vectorstore.COLLECTION)  # clean slate
    vectorstore.ensure_collection(client)
    assert client.collections.exists(vectorstore.COLLECTION)
    vectorstore.ensure_collection(client)  # second call must not raise
    assert client.collections.exists(vectorstore.COLLECTION)


class FakeEmbeddings(Embeddings):
    """Deterministic 3-d vectors: each known text maps to a distinct axis so
    near_vector returns a predictable nearest neighbour."""
    _MAP = {
        "alpha company founded by ada": [1.0, 0.0, 0.0],
        "beta company founded by bruno": [0.0, 1.0, 0.0],
        "gamma unrelated filler text": [0.0, 0.0, 1.0],
    }

    def embed_documents(self, texts):
        return [self._MAP[t] for t in texts]

    def embed_query(self, text):
        return self._MAP[text]


def test_build_index_then_search_returns_nearest(weaviate_available):
    client = weaviate_available
    client.collections.delete(vectorstore.COLLECTION)
    emb = FakeEmbeddings()
    chunks = [
        {"chunk_id": "a", "text": "alpha company founded by ada", "source": "a.txt"},
        {"chunk_id": "b", "text": "beta company founded by bruno", "source": "b.txt"},
        {"chunk_id": "g", "text": "gamma unrelated filler text", "source": "g.txt"},
    ]
    n = vectorstore.build_index(client, emb, chunks, tenant="demo")
    assert n == 3
    hits = vectorstore.search(client, emb, "alpha company founded by ada", k=1, tenant="demo")
    assert [h["chunk_id"] for h in hits] == ["a"]
    assert hits[0]["source"] == "a.txt"
    assert hits[0]["score"] > 0.9


def test_search_is_tenant_scoped(weaviate_available):
    client = weaviate_available
    client.collections.delete(vectorstore.COLLECTION)
    emb = FakeEmbeddings()
    vectorstore.build_index(client, emb, [
        {"chunk_id": "a", "text": "alpha company founded by ada", "source": "a.txt"},
    ], tenant="t1")
    hits = vectorstore.search(client, emb, "alpha company founded by ada", k=5, tenant="t2")
    assert hits == []   # different tenant sees nothing
