"""Optional MCP server exposing the graph service as MCP tools.

This is a STANDALONE, general-purpose surface, NOT the secured platform path.
The platform uses the mTLS REST wrapper (graphrag/api.py); this MCP server
has no mTLS and no client-cert allow-list, so `tenant` is a required tool
argument and the transport must be secured by whatever runs it (stdio for a
local client, or an auth'd HTTP transport). Do not expose it unauthenticated.

Tools: retrieve, ingest, delete, health — thin wrappers over the same service
functions the REST wrapper uses, sharing one pooled, lazily-opened Neo4j driver.

Run (stdio):  python -m graphrag.mcp_server
"""

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from graphrag.config import load_config
from graphrag.ingestion.pipeline import ingest_chunks as _ingest_chunks
from graphrag.ingestion.writer import create_constraints, delete_source as _delete_source, get_graph
from graphrag.retrieval.service import retrieve as _retrieve

mcp = FastMCP("graphrag")

_state: dict = {}


def _graph():
    """Lazily open and cache one pooled driver (so importing this module needs no DB)."""
    if "graph" not in _state:
        cfg = load_config("config.yaml")
        graph = get_graph(cfg)
        create_constraints(graph)
        _state["cfg"], _state["graph"] = cfg, graph
    return _state["cfg"], _state["graph"]


class Chunk(BaseModel):
    chunk_id: str
    text: str
    source: str = "unknown"


@mcp.tool()
def retrieve(tenant: str, chunk_ids: list[str], hops: int = 1,
             question: str | None = None, top_n: int | None = None) -> list[dict]:
    """Expand the tenant's graph from `chunk_ids` and return facts
    {subject, predicate, object}. If `question` is given, facts are reranked
    (local cross-encoder) and truncated to top_n."""
    cfg, graph = _graph()
    return _retrieve(graph, tenant, chunk_ids, hops=hops,
                     max_degree=cfg.expander.max_degree,
                     candidate_limit=cfg.expander.candidate_limit,
                     question=question,
                     top_n=top_n or cfg.expander.top_n,
                     rerank_model=cfg.expander.rerank_model)


@mcp.tool()
def ingest(tenant: str, chunks: list[Chunk]) -> dict:
    """Ingest pre-chunked [{chunk_id, text, source}] for a tenant. Extracts a
    graph, so the LLM gateway (OPENAI_BASE_URL/OPENAI_API_KEY) must be configured."""
    cfg, _ = _graph()
    return _ingest_chunks(cfg, tenant, [c.model_dump() for c in chunks])


@mcp.tool()
def delete(tenant: str, source: str) -> dict:
    """Delete a source's chunks, mentions, and orphaned entities for a tenant."""
    _, graph = _graph()
    return _delete_source(graph, tenant, source)


@mcp.tool()
def health() -> dict:
    """Liveness: confirm Neo4j is reachable."""
    _, graph = _graph()
    graph.query("RETURN 1 AS ok")
    return {"status": "ok"}


def main():
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
