"""Graph-retrieval service entrypoint (option b: graph-only).

The platform does its own Weaviate vector search and hands us the resulting
chunk_ids; we expand the graph and return {subject, predicate, object} facts.
No vector search happens here. Every query is tenant-scoped — tenant is
mandatory, there is no "see everything" fallback.

If the platform passes the `question` it searched with, facts are reranked by a
local cross-encoder and truncated to top_n; otherwise they come back in the
expander's deterministic order, truncated to top_n.
"""

import logging

from langchain_neo4j import Neo4jGraph

from graphrag.retrieval.expander import (
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_MAX_DEGREE,
    expand,
)
from graphrag.retrieval.rerank import rerank_available, rerank_facts

logger = logging.getLogger(__name__)


def retrieve(graph: Neo4jGraph, tenant: str, chunk_ids: list[str], hops: int = 1,
             max_degree: int = DEFAULT_MAX_DEGREE,
             candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
             question: str | None = None,
             top_n: int | None = None,
             rerank_model: str = "BAAI/bge-reranker-base") -> list[dict]:
    if not chunk_ids:
        return []
    facts = expand(graph, chunk_ids, hops=hops, tenant=tenant,
                   max_degree=max_degree, limit=candidate_limit)
    if question and rerank_available():
        # Fail closed: rerank_available() only confirms the package is importable.
        # The model can still be absent (fresh sidecar, no HF egress) or predict can
        # error — fall back to the deterministic expander order instead of 500ing.
        try:
            return rerank_facts(question, facts, top_n or len(facts), rerank_model)
        except Exception:
            logger.warning("rerank failed; falling back to deterministic order",
                           exc_info=True)
    return facts[:top_n] if top_n else facts
