from langchain_core.documents import Document
from langchain_neo4j import Neo4jGraph

from graphrag.config import Config

# Graph-only service (option b): Weaviate owns vectors, we store no embeddings.
# :Chunk is a lightweight anchor keyed by (chunk_id, tenant); :Document provenance
# is tenant-scoped too (two tenants may use the same source name).
CHUNK_WRITE = """
UNWIND $rows AS row
MERGE (d:Document {source: row.source, tenant: $tenant})
MERGE (c:Chunk {chunk_id: row.chunk_id, tenant: $tenant})
SET c.text = row.text
MERGE (d)-[:HAS_CHUNK]->(c)
"""

# Entities, with tenant IN THE MERGE KEY (not a post-write re-tag) so two tenants'
# identical entity name become two nodes and never cross-link. Native MERGE on the
# exact composite-constraint key (tenant, id) — it uses the constraint index, so it
# is correct under concurrency. (apoc.merge.node mis-handles composite constraints,
# flagging a false conflict on `id` alone; the label here is static so we don't need
# it. Dynamic relationship TYPES below still require APOC.)
ENTITY_WRITE = """
UNWIND $nodes AS n
MERGE (e:__Entity__ {tenant: $tenant, id: n.id})
SET e += n.props
"""
REL_WRITE = """
UNWIND $rels AS r
MERGE (a:__Entity__ {tenant: $tenant, id: r.source})
MERGE (b:__Entity__ {tenant: $tenant, id: r.target})
WITH a, b, r
CALL apoc.merge.relationship(a, r.type, {}, r.props, b, {}) YIELD rel
RETURN count(*)
"""
# Chunk -> entity links, created directly and scoped to the just-ingested chunks +
# tenant (task 2.5): no full-graph scan, no langchain :Document{id} indirection.
MENTIONS_WRITE = """
UNWIND $mentions AS m
MATCH (c:Chunk {tenant: $tenant, chunk_id: m.chunk_id})
MATCH (e:__Entity__ {tenant: $tenant, id: m.entity_id})
MERGE (c)-[:MENTIONS]->(e)
"""

CONSTRAINTS = [
    "CREATE CONSTRAINT chunk_tenant_key IF NOT EXISTS "
    "FOR (c:Chunk) REQUIRE (c.tenant, c.chunk_id) IS UNIQUE",
    "CREATE CONSTRAINT entity_tenant_key IF NOT EXISTS "
    "FOR (e:__Entity__) REQUIRE (e.tenant, e.id) IS UNIQUE",
]


def get_graph(cfg: Config) -> Neo4jGraph:
    return Neo4jGraph(
        url=cfg.neo4j.uri,
        username=cfg.neo4j.username,
        password=cfg.neo4j.password,
    )


# Delete a source's chunks (with HAS_CHUNK + MENTIONS via DETACH) and its :Document,
# returning the entities they mentioned as orphan candidates. Tenant-scoped throughout.
DELETE_SOURCE = """
MATCH (d:Document {source: $source, tenant: $tenant})
OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk {tenant: $tenant})
OPTIONAL MATCH (c)-[:MENTIONS]->(e:__Entity__ {tenant: $tenant})
WITH d, collect(DISTINCT c) AS chunks, collect(DISTINCT e.id) AS ent_ids
FOREACH (x IN chunks | DETACH DELETE x)
DETACH DELETE d
RETURN ent_ids
"""
# An entity is orphaned once no :Chunk of the same tenant mentions it any more.
DELETE_ORPHAN_ENTITIES = """
UNWIND $ent_ids AS eid
MATCH (e:__Entity__ {tenant: $tenant, id: eid})
WHERE NOT EXISTS { (:Chunk {tenant: $tenant})-[:MENTIONS]->(e) }
DETACH DELETE e
"""


def delete_source(graph: Neo4jGraph, tenant: str, source: str) -> dict:
    """Remove a source's :Chunk + :MENTIONS + :Document and any entities thereby
    orphaned, scoped to `tenant`. Idempotent: deleting an absent source is a no-op.
    Re-ingest reconciles content edits by source (chunk_id = SHA1 churns on edit).
    """
    rows = graph.query(DELETE_SOURCE, {"source": source, "tenant": tenant})
    ent_ids = rows[0]["ent_ids"] if rows else []
    if ent_ids:
        graph.query(DELETE_ORPHAN_ENTITIES, {"ent_ids": ent_ids, "tenant": tenant})
    return {"source": source, "tenant": tenant, "candidate_entities": len(ent_ids)}


def create_constraints(graph: Neo4jGraph) -> None:
    """Composite uniqueness on (tenant, chunk_id) and (tenant, id).

    Each CREATE CONSTRAINT runs in its own transaction (schema + data can't share
    one). The constraint — not MERGE — is what closes the concurrent-ingest race.
    """
    for stmt in CONSTRAINTS:
        graph.query(stmt)


def write_chunks(graph: Neo4jGraph, chunks: list[Document], tenant: str):
    rows = [
        {
            "source": c.metadata.get("source", "unknown"),
            "chunk_id": c.metadata["chunk_id"],
            "text": c.page_content,
        }
        for c in chunks
    ]
    graph.query(CHUNK_WRITE, {"rows": rows, "tenant": tenant})


def write_graph_tenant(graph: Neo4jGraph, graph_docs, tenant: str) -> None:
    """Tenant-scoped custom write: entities keyed by (tenant, id), their relationships,
    and :Chunk-[:MENTIONS]->entity edges — replacing langchain's global-id
    add_graph_documents on the service path.
    """
    nodes, rels, mentions = [], [], []
    for gd in graph_docs:
        chunk_id = gd.source.metadata["id"]
        for node in gd.nodes:
            nodes.append({"id": node.id, "props": {"type": node.type, **node.properties}})
            mentions.append({"chunk_id": chunk_id, "entity_id": node.id})
        for rel in gd.relationships:
            rels.append({
                "source": rel.source.id,
                "target": rel.target.id,
                "type": rel.type,
                "props": rel.properties,
            })

    if nodes:
        graph.query(ENTITY_WRITE, {"nodes": nodes, "tenant": tenant})
    if rels:
        graph.query(REL_WRITE, {"rels": rels, "tenant": tenant})
    if mentions:
        graph.query(MENTIONS_WRITE, {"mentions": mentions, "tenant": tenant})


# --- eval/debug only (single-tenant frozen replay): langchain global-id write -----
def write_graph_documents(graph: Neo4jGraph, graph_docs) -> None:
    graph.add_graph_documents(graph_docs, baseEntityLabel=True, include_source=True)


LINK_CHUNKS_TO_ENTITIES = """
MATCH (src:Document)-[:MENTIONS]->(e)
WHERE src.id IS NOT NULL
MATCH (c:Chunk {chunk_id: src.id})
MERGE (c)-[:MENTIONS]->(e)
"""


def link_chunks_to_entities(graph: Neo4jGraph) -> None:
    graph.query(LINK_CHUNKS_TO_ENTITIES)
