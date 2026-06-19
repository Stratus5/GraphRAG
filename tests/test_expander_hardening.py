"""Phase 4.3: expander hardening — clean facts (no MENTIONS/None) and the
super-node degree cap. The frozen eval can't trigger the cap (its entities are
low-degree), so it's covered here with a synthetic hub. Loopback Neo4j."""

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
from graphrag.retrieval.expander import expand
from tests.conftest import reset_schema


@pytest.fixture
def graph(neo4j_available):
    g = get_graph(load_config("config.yaml"))
    g.query("MATCH (n) DETACH DELETE n")
    reset_schema(g)
    create_constraints(g)
    return g


def test_facts_are_clean_entity_triples_only(graph):
    write_chunks(graph, [Document(page_content="t",
                 metadata={"id": "c1", "chunk_id": "c1", "source": "s.txt"})], tenant="A")
    acme, beta = Node(id="Acme Corp", type="Company"), Node(id="Beta Labs", type="Company")
    write_graph_tenant(graph, [GraphDocument(
        nodes=[acme, beta], relationships=[Relationship(source=acme, target=beta, type="ACQUIRED")],
        source=Document(page_content="t", metadata={"id": "c1", "source": "s.txt"}),
    )], tenant="A")

    facts = expand(graph, ["c1"], hops=2, tenant="A")

    assert facts  # real fact present
    assert all(f["subject"] is not None and f["object"] is not None for f in facts)
    assert all(f["predicate"] not in ("MENTIONS", "HAS_CHUNK") for f in facts)
    assert {(f["subject"], f["predicate"], f["object"]) for f in facts} == {
        ("Acme Corp", "ACQUIRED", "Beta Labs")}


def _build_hub(graph, fanout=10):
    # S -R-> H -R-> X, plus H -R-> n0..n{fanout-1}. H's entity-entity degree = fanout+2.
    graph.query(f"""
    CREATE (s:__Entity__ {{tenant:'T', id:'S'}})
    CREATE (h:__Entity__ {{tenant:'T', id:'H'}})
    CREATE (x:__Entity__ {{tenant:'T', id:'X'}})
    CREATE (c:Chunk {{tenant:'T', chunk_id:'cseed'}})
    CREATE (c)-[:MENTIONS]->(s)
    CREATE (s)-[:R]->(h)
    CREATE (h)-[:R]->(x)
    WITH h UNWIND range(0, {fanout - 1}) AS i
    CREATE (h)-[:R]->(:__Entity__ {{tenant:'T', id:'n'+toString(i)}})
    """)


def test_degree_cap_blocks_expansion_through_hub(graph):
    _build_hub(graph, fanout=10)  # H degree = 12
    facts = {(f["subject"], f["predicate"], f["object"])
             for f in expand(graph, ["cseed"], hops=2, tenant="T", max_degree=5)}
    assert ("S", "R", "H") in facts          # H as a terminal fact is fine
    assert ("H", "R", "X") not in facts      # but we don't expand THROUGH the hub
    assert not any(s == "H" for s, _, _ in facts)  # no H->n* blow-up


def test_without_cap_expansion_passes_through_hub(graph):
    _build_hub(graph, fanout=10)
    facts = {(f["subject"], f["predicate"], f["object"])
             for f in expand(graph, ["cseed"], hops=2, tenant="T", max_degree=50)}
    assert ("S", "R", "H") in facts
    assert ("H", "R", "X") in facts          # high cap -> the hub is traversable
