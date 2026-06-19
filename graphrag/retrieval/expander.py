from langchain_neo4j import Neo4jGraph

DEFAULT_MAX_DEGREE = 50
# Candidates are ordered by hop distance before this cut, so a low limit can drop
# far-but-relevant facts before the reranker scores them. Headroom over the eval's
# tens of facts; tiered sampling (all near hops + sampled far) is the real fix.
DEFAULT_CANDIDATE_LIMIT = 500


def build_expansion_query(hops: int = 1) -> str:
    """Facts (entity→entity triples) reachable from the given chunks, tenant-scoped.

    Cleaned + bounded for clean LLM context:
    - every path node must be a tenant `:__Entity__`, so traversal never crosses
      MENTIONS/HAS_CHUNK or an id-less :Chunk/:Document node — no junk facts;
    - intermediate waypoints with entity-entity degree above $max_degree are not
      expanded *through* (super-node cap), though a hub may still be a terminal fact;
    - results are ordered by (min hop distance, then S/P/O) before $limit, so the
      candidate set is deterministic and prefers closer facts.
    """
    return f"""
    MATCH (c:Chunk)
    WHERE c.chunk_id IN $chunk_ids AND c.tenant = $tenant
    MATCH (c)-[:MENTIONS]->(e:__Entity__ {{tenant: $tenant}})
    MATCH path = (e)-[*1..{hops}]-(neighbor:__Entity__)
    WHERE all(n IN nodes(path) WHERE n.tenant = $tenant AND n:__Entity__)
      AND all(m IN nodes(path)[1..-1]
              WHERE COUNT {{ (m)--(:__Entity__ {{tenant: $tenant}}) }} <= $max_degree)
    WITH relationships(path) AS rels
    UNWIND range(0, size(rels) - 1) AS i
    WITH startNode(rels[i]).id AS subject,
         type(rels[i]) AS predicate,
         endNode(rels[i]).id AS object,
         i + 1 AS hop
    WHERE subject IS NOT NULL AND object IS NOT NULL
    WITH subject, predicate, object, min(hop) AS hop
    RETURN subject, predicate, object
    ORDER BY hop, subject, predicate, object
    LIMIT $limit
    """


def expand(graph: Neo4jGraph, chunk_ids: list[str], hops: int, tenant: str,
           max_degree: int = DEFAULT_MAX_DEGREE,
           limit: int = DEFAULT_CANDIDATE_LIMIT) -> list[dict]:
    if not chunk_ids:
        return []
    return graph.query(build_expansion_query(hops), {
        "chunk_ids": chunk_ids, "tenant": tenant,
        "max_degree": max_degree, "limit": limit,
    })
