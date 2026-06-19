from langchain_core.documents import Document
from graphrag.ingestion.chunker import chunk_documents


def test_chunk_splits_long_text():
    doc = Document(page_content="word " * 1000, metadata={"source": "a.txt"})
    chunks = chunk_documents([doc], size=200, overlap=20)
    assert len(chunks) > 1
    assert all(c.metadata["source"] == "a.txt" for c in chunks)
    assert all("chunk_id" in c.metadata for c in chunks)
    assert all(c.metadata["id"] == c.metadata["chunk_id"] for c in chunks)


def test_chunk_ids_are_unique():
    doc = Document(page_content="word " * 1000, metadata={"source": "a.txt"})
    chunks = chunk_documents([doc], size=200, overlap=20)
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
