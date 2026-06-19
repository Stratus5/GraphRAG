from graphrag.retrieval.qa import build_context


def test_build_context_includes_chunks_and_facts():
    chunks = [{"text": "Jane founded Acme.", "source": "a.txt", "chunk_id": "1"}]
    facts = [{"subject": "Jane", "predicate": "FOUNDED", "object": "Acme"}]
    context = build_context(chunks, facts)
    assert "Jane founded Acme." in context
    assert "Jane FOUNDED Acme" in context
    assert "a.txt" in context


def test_build_context_handles_no_facts():
    chunks = [{"text": "Some text.", "source": "b.txt", "chunk_id": "2"}]
    context = build_context(chunks, [])
    assert "Some text." in context
