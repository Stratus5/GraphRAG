from graphrag import vectorstore
from graphrag.config import Config
from graphrag.ingestion.writer import get_graph
from graphrag.providers import get_chat_model, get_embeddings
from graphrag.retrieval.expander import expand
from graphrag.retrieval.qa import answer


def query(cfg: Config, question: str, k: int = 4, hops: int = 1, tenant: str = "default") -> str:
    """Eval/debug path (vector + graph). The service path is service.retrieve.

    Real vector search via Weaviate (graphrag.vectorstore) -> chunk_ids -> graph
    expansion (Neo4j) -> grounded answer. Empty expansion -> chunks-only answer.
    """
    graph = get_graph(cfg)
    client = vectorstore.connect()
    try:
        hits = vectorstore.search(client, get_embeddings(cfg), question, k=k, tenant=tenant)
    finally:
        client.close()
    chunk_ids = [h["chunk_id"] for h in hits]
    facts = expand(graph, chunk_ids, hops=hops, tenant=tenant)
    return answer(get_chat_model(cfg), question, hits, facts)
