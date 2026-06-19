from pathlib import Path

from graphrag.config import load_config


def test_load_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "llm:\n  provider: openai\n  model: gpt-4o-mini\n"
        "embeddings:\n  provider: openai\n  model: text-embedding-3-small\n"
        "chunking:\n  size: 1000\n  overlap: 200\n"
        "schema:\n  allowed_nodes: []\n  allowed_relationships: []\n"
    )
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    cfg = load_config(cfg_file)
    assert cfg.llm.provider == "openai"
    assert cfg.chunking.size == 1000
    assert cfg.neo4j.uri == "bolt://localhost:7687"
    assert cfg.schema.allowed_nodes == []
