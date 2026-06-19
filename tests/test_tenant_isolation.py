"""Phase 2 gate (security-critical): tenant A's retrieve() never returns tenant
B's facts, covering both :Chunk scoping and shared-entity cross-linking.

Deterministic (no LLM): graph documents are built by hand and written through
the real tenant write path, so this cannot flake. Runs against loopback Neo4j.
"""

import pytest
from langchain_community.graphs.graph_document import GraphDocument, Node, Relationship
from langchain_core.documents import Document

from graphrag.config import load_config
from graphrag.ingestion.writer import (
    create_constraints,
    get_graph,
    write_chunks,
    write_graph_tenant,
)
from graphrag.retrieval.service import retrieve
from tests.conftest import reset_schema


def _graph_doc(chunk_id: str, source: str, acquired: str) -> GraphDocument:
    # Acme Corp -ACQUIRED-> <acquired>, both extracted from `chunk_id`.
    acme = Node(id="Acme Corp", type="Company")
    target = Node(id=acquired, type="Company")
    return GraphDocument(
        nodes=[acme, target],
        relationships=[Relationship(source=acme, target=target, type="ACQUIRED")],
        source=Document(page_content="Acme Corp acquired a company.",
                        metadata={"id": chunk_id, "source": source}),
    )


def _chunk_doc(chunk_id: str, source: str) -> Document:
    return Document(page_content="Acme Corp acquired a company.",
                    metadata={"id": chunk_id, "chunk_id": chunk_id, "source": source})


@pytest.fixture
def two_tenants(neo4j_available):
    graph = get_graph(load_config("config.yaml"))
    graph.query("MATCH (n) DETACH DELETE n")
    reset_schema(graph)
    create_constraints(graph)
    # Both tenants ingest an entity named "Acme Corp" with a DISTINCT neighbour.
    write_chunks(graph, [_chunk_doc("cA", "a.txt")], tenant="A")
    write_graph_tenant(graph, [_graph_doc("cA", "a.txt", "Alpha Co")], tenant="A")
    write_chunks(graph, [_chunk_doc("cB", "b.txt")], tenant="B")
    write_graph_tenant(graph, [_graph_doc("cB", "b.txt", "Bravo Co")], tenant="B")
    return graph


def _entities(facts):
    return {f["subject"] for f in facts} | {f["object"] for f in facts}


def test_retrieve_returns_only_own_tenant_facts(two_tenants):
    a = retrieve(two_tenants, "A", ["cA"], hops=2)
    b = retrieve(two_tenants, "B", ["cB"], hops=2)
    assert "Alpha Co" in _entities(a) and "Bravo Co" not in _entities(a)
    assert "Bravo Co" in _entities(b) and "Alpha Co" not in _entities(b)


def test_other_tenants_chunk_id_returns_nothing(two_tenants):
    # A presenting B's chunk_id must yield nothing: the :Chunk is tenant-scoped.
    assert retrieve(two_tenants, "A", ["cB"], hops=2) == []


def test_shared_entity_name_is_two_nodes_never_cross_linked(two_tenants):
    n = two_tenants.query(
        "MATCH (e:__Entity__ {id: 'Acme Corp'}) RETURN count(e) AS n")[0]["n"]
    assert n == 2  # one Acme per tenant, not a single merged node
    cross = two_tenants.query(
        "MATCH (a:__Entity__ {tenant: 'A'})-[]-(b:__Entity__ {tenant: 'B'}) "
        "RETURN count(*) AS n")[0]["n"]
    assert cross == 0


def test_chunk_never_mentions_other_tenant_entity(two_tenants):
    # :Chunk-level cross-linking: an A chunk must never MENTIONS a B entity (or vice versa).
    cross = two_tenants.query(
        "MATCH (c:Chunk)-[:MENTIONS]->(e:__Entity__) WHERE c.tenant <> e.tenant "
        "RETURN count(*) AS n")[0]["n"]
    assert cross == 0


def test_same_chunk_id_across_tenants_stays_isolated(neo4j_available):
    # Platform chunk_ids can collide across tenants; the (tenant, chunk_id) key +
    # c.tenant filter must keep them separate.
    graph = get_graph(load_config("config.yaml"))
    graph.query("MATCH (n) DETACH DELETE n")
    reset_schema(graph)
    create_constraints(graph)
    write_chunks(graph, [_chunk_doc("dup", "a.txt")], tenant="A")
    write_graph_tenant(graph, [_graph_doc("dup", "a.txt", "Alpha Co")], tenant="A")
    write_chunks(graph, [_chunk_doc("dup", "b.txt")], tenant="B")
    write_graph_tenant(graph, [_graph_doc("dup", "b.txt", "Bravo Co")], tenant="B")

    # two distinct :Chunk nodes share chunk_id "dup", one per tenant
    assert graph.query("MATCH (c:Chunk {chunk_id:'dup'}) RETURN count(c) AS n")[0]["n"] == 2
    a = _entities(retrieve(graph, "A", ["dup"], hops=2))
    b = _entities(retrieve(graph, "B", ["dup"], hops=2))
    assert "Alpha Co" in a and "Bravo Co" not in a
    assert "Bravo Co" in b and "Alpha Co" not in b
