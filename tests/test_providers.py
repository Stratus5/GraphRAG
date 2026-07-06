from graphrag import providers
from graphrag.config import load_config


def _cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "llm:\n  provider: openai\n  model: fc:openai/gpt-4o-mini\n"
        "embeddings:\n  provider: openai\n  model: fc:openai/text-embedding-3-small\n"
        "chunking:\n  size: 1000\n  overlap: 200\n"
        "schema:\n  allowed_nodes: []\n  allowed_relationships: []\n"
    )
    return load_config(cfg_file)


def test_gateway_embeddings_send_strings_not_token_arrays(tmp_path, monkeypatch):
    """Against the LLM gateway, OpenAIEmbeddings must NOT tiktoken-encode inputs into
    integer token-ID arrays (langchain's default). The gateway rejects token arrays with
    `400 invalid_input: Each 'input' array item must be a string`; it requires raw
    strings. So check_embedding_ctx_length must be False whenever a gateway base_url
    is configured."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(providers, "_BASE_URL", "https://gw.example/v1")
    emb = providers.get_embeddings(_cfg(tmp_path, monkeypatch))
    assert emb.check_embedding_ctx_length is False


def test_direct_openai_keeps_ctx_length_check(tmp_path, monkeypatch):
    """Against api.openai.com (no gateway base_url) the default length-safety path is
    preserved — real OpenAI accepts token arrays and splits over-long inputs itself."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(providers, "_BASE_URL", None)
    emb = providers.get_embeddings(_cfg(tmp_path, monkeypatch))
    assert emb.check_embedding_ctx_length is True
