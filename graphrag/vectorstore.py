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
