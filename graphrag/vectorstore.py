"""Weaviate-backed vector search — a reusable graphrag capability for the CLI, eval,
and demo. NOT part of the mTLS service path (see tests/test_boundary.py): the platform
owns vectors in production; this lets local/CLI/demo do their own vector search.

Vectors are bring-your-own (Weaviate runs with vectorizer 'none'); embeddings are
supplied by the caller as a langchain Embeddings object (gateway-backed in real use,
faked in tests). Tenant is a property, filtered on every query.
"""
import os

import weaviate
from langchain_core.embeddings import Embeddings
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.query import Filter, MetadataQuery
from weaviate.util import generate_uuid5

COLLECTION = "Chunk"


def connect() -> weaviate.WeaviateClient:
    """Open a Weaviate client from env (caller must client.close())."""
    return weaviate.connect_to_local(
        host=os.environ.get("WEAVIATE_HOST", "localhost"),
        port=int(os.environ.get("WEAVIATE_PORT", "8080")),
        grpc_port=int(os.environ.get("WEAVIATE_GRPC_PORT", "50051")),
    )


def ensure_collection(client: weaviate.WeaviateClient) -> None:
    """Create the Chunk collection (vectorizer none) if absent. Idempotent."""
    if client.collections.exists(COLLECTION):
        return
    client.collections.create(
        name=COLLECTION,
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(name="chunk_id", data_type=DataType.TEXT),
            Property(name="text", data_type=DataType.TEXT),
            Property(name="source", data_type=DataType.TEXT),
            Property(name="tenant", data_type=DataType.TEXT),
        ],
    )


def build_index(client: weaviate.WeaviateClient, embeddings: Embeddings,
                chunks: list[dict], tenant: str) -> int:
    """Embed and upsert chunks for `tenant`. Deterministic uuid -> re-runs upsert
    (idempotent), matching the graph side's MERGE semantics."""
    if not chunks:
        return 0
    ensure_collection(client)
    vectors = embeddings.embed_documents([c["text"] for c in chunks])
    coll = client.collections.get(COLLECTION)
    with coll.batch.dynamic() as batch:
        for c, vec in zip(chunks, vectors):
            batch.add_object(
                properties={
                    "chunk_id": c["chunk_id"],
                    "text": c["text"],
                    "source": c.get("source", "unknown"),
                    "tenant": tenant,
                },
                uuid=generate_uuid5(f"{tenant}:{c['chunk_id']}"),
                vector=vec,
            )
    return len(chunks)


def search(client: weaviate.WeaviateClient, embeddings: Embeddings,
           question: str, k: int, tenant: str) -> list[dict]:
    """Vector search within `tenant`; returns [{chunk_id, text, source, score}]."""
    coll = client.collections.get(COLLECTION)
    res = coll.query.near_vector(
        near_vector=embeddings.embed_query(question),
        limit=k,
        filters=Filter.by_property("tenant").equal(tenant),
        return_metadata=MetadataQuery(distance=True),
    )
    return [
        {
            "chunk_id": o.properties["chunk_id"],
            "text": o.properties["text"],
            "source": o.properties["source"],
            "score": 1.0 - (o.metadata.distance or 0.0),
        }
        for o in res.objects
    ]
