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

        return OpenAIEmbeddings(model=cfg.embeddings.model, base_url=_BASE_URL)
    raise ValueError(f"Unsupported embeddings provider: {provider}")
