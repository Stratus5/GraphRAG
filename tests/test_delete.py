"""Phase 3.1: delete(tenant, source) removes that source's chunks, MENTIONS, and
orphaned entities — tenant-scoped — and re-ingest doesn't leave stale content.

Deterministic (hand-built graph docs, no LLM). Loopback Neo4j.
"""

import pytest
from langchain_community.graphs.graph_document import GraphDocument, Node, Relationship
from langchain_core.documents import Document

from graphrag.config import load_config
from graphrag.ingestion.writer import (
    create_constraints,
    delete_source,
    get_graph,
    write_chunks,
    write_graph_tenant,
)
from graphrag.retrieval.service import retrieve
from tests.conftest import reset_schema


def _chunk(chunk_id, source):
    return Document(page_content="text",
                    metadata={"id": chunk_id, "chunk_id": chunk_id, "source": source})


def _graph_doc(chunk_id, source, head, tail):
    h, t = Node(id=head, type="Company"), Node(id=tail, type="Company")
    return GraphDocument(nodes=[h, t],
                         relationships=[Relationship(source=h, target=t, type="ACQUIRED")],
                         source=Document(page_content="text",
                                         metadata={"id": chunk_id, "source": source}))


def _write(graph, tenant, chunk_id, source, head, tail):
    write_chunks(graph, [_chunk(chunk_id, source)], tenant=tenant)
    write_graph_tenant(graph, [_graph_doc(chunk_id, source, head, tail)], tenant=tenant)


def _count(graph, cypher, **params):
    return graph.query(cypher, params)[0]["n"]


@pytest.fixture
def graph(neo4j_available):
    g = get_graph(load_config("config.yaml"))
    g.query("MATCH (n) DETACH DELETE n")
    reset_schema(g)
    create_constraints(g)
    return g


def test_delete_removes_chunk_mentions_and_orphaned_entities(graph):
    _write(graph, "A", "cA", "a.txt", "Acme Corp", "Alpha Co")
    assert retrieve(graph, "A", ["cA"], hops=2)  # sanity: facts present first

    delete_source(graph, "A", "a.txt")

    assert _count(graph, "MATCH (c:Chunk {tenant:'A'}) RETURN count(c) AS n") == 0
    assert _count(graph, "MATCH (d:Document {tenant:'A'}) RETURN count(d) AS n") == 0
    assert _count(graph, "MATCH (e:__Entity__ {tenant:'A'}) RETURN count(e) AS n") == 0
    assert retrieve(graph, "A", ["cA"], hops=2) == []


def test_delete_is_tenant_scoped(graph):
    _write(graph, "A", "cA", "shared.txt", "Acme Corp", "Alpha Co")
    _write(graph, "B", "cB", "shared.txt", "Acme Corp", "Bravo Co")

    delete_source(graph, "A", "shared.txt")

    assert _count(graph, "MATCH (c:Chunk {tenant:'A'}) RETURN count(c) AS n") == 0
    # tenant B untouched
    assert _count(graph, "MATCH (c:Chunk {tenant:'B'}) RETURN count(c) AS n") == 1
    assert "Bravo Co" in {f["object"] for f in retrieve(graph, "B", ["cB"], hops=2)}


def test_entity_kept_if_another_source_still_mentions_it(graph):
    _write(graph, "A", "c1", "s1.txt", "Acme Corp", "Alpha Co")
    _write(graph, "A", "c2", "s2.txt", "Acme Corp", "Gamma Co")  # also mentions Acme Corp

    delete_source(graph, "A", "s1.txt")

    # Acme Corp still mentioned by s2's chunk -> not orphaned
    assert _count(graph, "MATCH (e:__Entity__ {tenant:'A', id:'Acme Corp'}) RETURN count(e) AS n") == 1
    # Alpha Co was only in s1 -> orphaned and gone
    assert _count(graph, "MATCH (e:__Entity__ {tenant:'A', id:'Alpha Co'}) RETURN count(e) AS n") == 0


def test_reingest_after_edit_leaves_no_stale_content(graph):
    # edit churns chunk_id (SHA1) -> reconcile by source: delete then re-write.
    _write(graph, "A", "old", "doc.txt", "Old Co", "Sub One")
    delete_source(graph, "A", "doc.txt")
    _write(graph, "A", "new", "doc.txt", "New Co", "Sub Two")

    ids = {e["id"] for e in graph.query("MATCH (e:__Entity__ {tenant:'A'}) RETURN e.id AS id")}
    assert ids == {"New Co", "Sub Two"}
    assert _count(graph, "MATCH (c:Chunk {tenant:'A', chunk_id:'old'}) RETURN count(c) AS n") == 0
