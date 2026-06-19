from langchain_core.documents import Document
from graphrag.ingestion.extractor import build_transformer

def test_build_transformer_generic(monkeypatch):
    # Generic mode: empty schema -> transformer constructed with no node/rel limits
    captured = {}

    class FakeTransformer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "graphrag.ingestion.extractor.LLMGraphTransformer", FakeTransformer
    )
    build_transformer(llm=object(), allowed_nodes=[], allowed_relationships=[])
    assert captured["allowed_nodes"] == []
    assert captured["allowed_relationships"] == []

def test_build_transformer_domain(monkeypatch):
    captured = {}

    class FakeTransformer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "graphrag.ingestion.extractor.LLMGraphTransformer", FakeTransformer
    )
    build_transformer(
        llm=object(),
        allowed_nodes=["Person", "Company"],
        allowed_relationships=["FOUNDED"],
    )
    assert captured["allowed_nodes"] == ["Person", "Company"]
    assert captured["allowed_relationships"] == ["FOUNDED"]
