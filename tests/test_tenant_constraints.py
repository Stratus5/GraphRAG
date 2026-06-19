"""Phase 2.3: composite uniqueness constraints dedupe entities per tenant under
concurrent ingest. Tests are written to prove the CONSTRAINT (not MERGE) closes
the race: the constraint must exist, and a direct duplicate CREATE must fail.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from neo4j import GraphDatabase

from graphrag.config import load_config
from graphrag.ingestion.writer import create_constraints, get_graph
from tests.conftest import reset_schema


@pytest.fixture
def clean_graph(neo4j_available):
    graph = get_graph(load_config("config.yaml"))
    graph.query("MATCH (n) DETACH DELETE n")
    reset_schema(graph)
    create_constraints(graph)
    return graph


def test_constraints_are_installed(clean_graph):
    rows = clean_graph.query(
        "SHOW CONSTRAINTS YIELD labelsOrTypes, properties "
        "RETURN labelsOrTypes AS labels, properties AS props")
    installed = {(tuple(r["labels"]), tuple(r["props"])) for r in rows}
    assert (("Chunk",), ("tenant", "chunk_id")) in installed
    assert (("__Entity__",), ("tenant", "id")) in installed


def test_duplicate_entity_create_violates_constraint(clean_graph):
    clean_graph.query("CREATE (:__Entity__ {tenant: 'Z', id: 'Dup'})")
    with pytest.raises(Exception) as exc:
        clean_graph.query("CREATE (:__Entity__ {tenant: 'Z', id: 'Dup'})")
    assert "constraint" in str(exc.value).lower()


def test_concurrent_merge_dedupes_to_one_node(clean_graph):
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    auth = (os.environ.get("NEO4J_USERNAME", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "password123"))
    driver = GraphDatabase.driver(uri, auth=auth)

    def merge_acme(_):
        # Same native MERGE the service write path uses.
        with driver.session() as s:
            s.run("MERGE (e:__Entity__ {tenant: 'C', id: 'Race'})")

    try:
        with ThreadPoolExecutor(max_workers=16) as ex:
            list(ex.map(merge_acme, range(64)))
    finally:
        driver.close()

    n = clean_graph.query(
        "MATCH (e:__Entity__ {tenant: 'C', id: 'Race'}) RETURN count(e) AS n")[0]["n"]
    assert n == 1
