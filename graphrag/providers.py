import os

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from graphrag.config import Config

# Extraction routes through the platform LLM gateway. Set in .env:
#   OPENAI_BASE_URL=https://api.fightclub.pro/v1
#   OPENAI_API_KEY=<gateway token>   (see docs/fightclub/INTEGRATION-SPEC.md)
# Left unset, langchain falls back to api.openai.com with the same key var.
_BASE_URL = os.environ.get("OPENAI_BASE_URL") or None


def get_chat_model(cfg: Config) -> BaseChatModel:
    provider = cfg.llm.provider
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=cfg.llm.model, temperature=0, base_url=_BASE_URL)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def get_embeddings(cfg: Config) -> Embeddings:
    provider = cfg.embeddings.provider
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        # The LLM gateway requires each `input` item to be a raw string. LangChain's
        # default (check_embedding_ctx_length=True) tiktoken-encodes text into integer
        # token-ID arrays, which api.openai.com accepts but the gateway rejects with
        # `400 invalid_input: Each 'input' array item must be a string`. Disable it on
        # the gateway path so strings are sent; keep the default (client-side
        # context-length splitting) when talking to api.openai.com directly.
        return OpenAIEmbeddings(
            model=cfg.embeddings.model,
            base_url=_BASE_URL,
            check_embedding_ctx_length=_BASE_URL is None,
        )
    raise ValueError(f"Unsupported embeddings provider: {provider}")
