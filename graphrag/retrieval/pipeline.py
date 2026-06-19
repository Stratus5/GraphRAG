from graphrag.config import Config
from graphrag.ingestion.writer import get_graph
from graphrag.providers import get_chat_model, get_embeddings
from graphrag.retrieval.expander import expand
from graphrag.retrieval.qa import answer
from graphrag.retrieval.vector import search


def query(cfg: Config, question: str, k: int = 4, hops: int = 1, tenant: str = "default") -> str:
    # Eval/debug path only (vector+graph). The service path is service.retrieve.
    graph = get_graph(cfg)
    chunks = search(graph, get_embeddings(cfg), question, k=k)
    chunk_ids = [c["chunk_id"] for c in chunks]
    facts = expand(graph, chunk_ids, hops=hops, tenant=tenant)  # empty -> chunks only
    return answer(get_chat_model(cfg), question, chunks, facts)
