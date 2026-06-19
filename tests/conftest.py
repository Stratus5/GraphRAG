import os

import pytest


def reset_schema(graph):
    """Drop every constraint so a test starts from a known clean schema.

    Needed because the eval bench writes via langchain add_graph_documents, which
    auto-creates a SINGLE-property :__Entity__(id) uniqueness constraint. That
    conflicts with multi-tenancy (same entity id across tenants). The production
    service never runs add_graph_documents, so its DB only ever has the composite
    (tenant,id) / (tenant,chunk_id) constraints — this only bites the shared dev DB.
    """
    for c in graph.query("SHOW CONSTRAINTS YIELD name RETURN name"):
        graph.query(f"DROP CONSTRAINT {c['name']} IF EXISTS")


@pytest.fixture
def neo4j_available():
    """Skip integration tests unless a live Neo4j is reachable."""
    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    try:
        driver = GraphDatabase.driver(
            uri,
            auth=(os.environ.get("NEO4J_USERNAME", "neo4j"),
                  os.environ.get("NEO4J_PASSWORD", "password123")),
        )
        driver.verify_connectivity()
        driver.close()
    except Exception:
        pytest.skip("Neo4j not available")
