from langchain_core.embeddings import Embeddings
from langchain_neo4j import Neo4jGraph

VECTOR_SEARCH = """
CALL db.index.vector.queryNodes('chunk_embedding', $k, $embedding)
YIELD node, score
MATCH (d:Document)-[:HAS_CHUNK]->(node)
RETURN node.chunk_id AS chunk_id, node.text AS text,
       d.source AS source, score
ORDER BY score DESC
"""


def search(graph: Neo4jGraph, embeddings: Embeddings, query: str, k: int = 4) -> list[dict]:
    vector = embeddings.embed_query(query)
    return graph.query(VECTOR_SEARCH, {"k": k, "embedding": vector})
