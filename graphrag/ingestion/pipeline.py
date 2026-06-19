from pathlib import Path
from typing import Callable

from langchain_core.documents import Document

from graphrag.config import Config
from graphrag.ingestion.chunker import chunk_documents
from graphrag.ingestion.extractor import build_transformer, extract_graph
from graphrag.ingestion.loaders import load_folder
from graphrag.ingestion.writer import (
    create_constraints,
    delete_source,
    get_graph,
    write_chunks,
    write_graph_tenant,
)
from graphrag import vectorstore
from graphrag.providers import get_chat_model, get_embeddings

Progress = Callable[[str, int, int], None] | None


def _noop(stage: str, current: int = 0, total: int = 0):
    pass


def _ingest_documents(
    cfg: Config, docs: list[Document], tenant: str, on_progress: Progress = None,
    graph=None,
) -> dict:
    """Shared core: extract a graph from already-chunked Documents and write it,
    tenant-scoped. Each Document MUST carry metadata["chunk_id"] and
    metadata["id"]==chunk_id. No embeddings — Weaviate owns vectors (option b).

    `graph` lets a long-lived caller (the API) pass its pooled driver; left None
    (CLI/eval) it opens a short-lived one.
    """
    p = on_progress or _noop

    transformer = build_transformer(
        llm=get_chat_model(cfg),
        allowed_nodes=cfg.schema.allowed_nodes,
        allowed_relationships=cfg.schema.allowed_relationships,
    )
    graph_docs, failures = extract_graph(
        transformer, docs,
        on_progress=lambda i: p("Extracting graph", i, len(docs)),
    )

    graph = graph or get_graph(cfg)
    create_constraints(graph)

    # Reconcile by source: re-ingesting a source replaces it, so edited content
    # (whose SHA1 chunk_ids churn) leaves no stale chunks/entities behind.
    for source in {d.metadata.get("source", "unknown") for d in docs}:
        delete_source(graph, tenant, source)

    p("Writing chunks", 0, 0)
    write_chunks(graph, docs, tenant)
    p("Writing chunks", len(docs), len(docs))

    # Tenant-scoped custom write: entities keyed by (tenant, id), their relationships,
    # and scoped :Chunk-[:MENTIONS]->entity links (no full-graph scan).
    p("Writing graph documents", 0, 0)
    write_graph_tenant(graph, graph_docs, tenant)
    p("Writing graph documents", len(graph_docs), len(graph_docs))

    return {
        "chunks": len(docs),
        "graph_documents": len(graph_docs),
        "extraction_failures": failures,
    }


def _documents_from_chunks(chunks: list[dict]) -> list[Document]:
    """Pre-chunked platform input [{chunk_id, text, source}] -> Documents.

    Sets metadata["id"]=chunk_id so write_graph_tenant can tie each extracted
    entity back to its source :Chunk for the :MENTIONS link.
    """
    return [
        Document(
            page_content=c["text"],
            metadata={
                "id": c["chunk_id"],
                "chunk_id": c["chunk_id"],
                "source": c.get("source", "unknown"),
            },
        )
        for c in chunks
    ]


def ingest_chunks(cfg: Config, tenant: str, chunks: list[dict],
                  on_progress: Progress = None, graph=None) -> dict:
    """Platform ingest path: caller supplies tenant + pre-chunked
    {chunk_id, text, source}. Bypasses loaders/chunker (those are eval-only).
    The platform is the chunk authority; chunk_id is its key into Weaviate.
    Pass `graph` to reuse a pooled driver (the API does).
    """
    return _ingest_documents(cfg, _documents_from_chunks(chunks), tenant, on_progress, graph=graph)


def ingest(cfg: Config, folder: Path | str, tenant: str = "default",
           on_progress: Progress = None) -> dict:
    """Eval/CLI ingest path: load + chunk a folder of files, then ingest.

    loaders.py + chunker.py are used only here, not on the platform path.
    """
    p = on_progress or _noop
    p("Loading documents", 0, 0)
    docs = load_folder(folder)
    p("Loading documents", len(docs), len(docs))

    p("Chunking", 0, 0)
    chunks = chunk_documents(docs, cfg.chunking.size, cfg.chunking.overlap)
    p("Chunking", len(chunks), len(chunks))

    stats = _ingest_documents(cfg, chunks, tenant, on_progress)
    stats["documents"] = len(docs)

    # CLI/eval entrypoint only: also build the Weaviate vector index so `graphrag query`
    # works end-to-end. The shared core (_ingest_documents / ingest_chunks, used by the
    # graph-only service) never does this — keeps the service-path invariant intact.
    rows = [
        {"chunk_id": c.metadata["chunk_id"], "text": c.page_content,
         "source": c.metadata.get("source", "unknown")}
        for c in chunks
    ]
    p("Building vector index", 0, 0)
    client = vectorstore.connect()
    try:
        vectorstore.build_index(client, get_embeddings(cfg), rows, tenant)
    finally:
        client.close()
    p("Building vector index", len(rows), len(rows))

    return stats
