"""The optional MCP server. Tools wrap the same tenant-scoped service functions;
an MCP client can search a tenant's graph. Loopback Neo4j, no gateway
(retrieve/delete/health are graph-only; ingest needs the LLM and isn't called)."""

import asyncio
import json

import pytest
from langchain_community.graphs.graph_document import GraphDocument, Node, Relationship
from langchain_core.documents import Document
from mcp.shared.memory import create_connected_server_and_client_session as connect

from graphrag import mcp_server
from graphrag.config import load_config
from graphrag.ingestion.writer import create_constraints, get_graph, write_chunks, write_graph_tenant
from tests.conftest import reset_schema


def _write(graph, tenant, chunk_id, source, head, tail):
    write_chunks(graph, [Document(page_content="t",
                 metadata={"id": chunk_id, "chunk_id": chunk_id, "source": source})], tenant=tenant)
    h, t = Node(id=head, type="Company"), Node(id=tail, type="Company")
    write_graph_tenant(graph, [GraphDocument(
        nodes=[h, t], relationships=[Relationship(source=h, target=t, type="ACQUIRED")],
        source=Document(page_content="t", metadata={"id": chunk_id, "source": source}),
    )], tenant=tenant)


@pytest.fixture
def seeded(neo4j_available):
    g = get_graph(load_config("config.yaml"))
    g.query("MATCH (n) DETACH DELETE n")
    reset_schema(g)
    create_constraints(g)
    _write(g, "A", "cA", "a.txt", "Acme Corp", "Alpha Co")
    _write(g, "B", "cB", "b.txt", "Acme Corp", "Bravo Co")
    g.close()
    mcp_server._state.clear()  # force the server to re-open against the seeded DB
    yield
    mcp_server._state.clear()


def _ents(facts):
    return {f["object"] for f in facts} | {f["subject"] for f in facts}


def test_tools_are_registered(seeded):
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"retrieve", "ingest", "delete", "health"} <= names


def test_retrieve_tool_is_tenant_scoped(seeded):
    a = mcp_server.retrieve(tenant="A", chunk_ids=["cA"], hops=2)
    b = mcp_server.retrieve(tenant="B", chunk_ids=["cB"], hops=2)
    assert "Alpha Co" in _ents(a) and "Bravo Co" not in _ents(a)
    assert "Bravo Co" in _ents(b) and "Alpha Co" not in _ents(b)
    # other tenant's chunk id -> nothing
    assert mcp_server.retrieve(tenant="A", chunk_ids=["cB"], hops=2) == []


def test_health_and_delete_tools(seeded):
    assert mcp_server.health() == {"status": "ok"}
    mcp_server.delete(tenant="A", source="a.txt")
    assert mcp_server.retrieve(tenant="A", chunk_ids=["cA"], hops=2) == []
    assert "Bravo Co" in _ents(mcp_server.retrieve(tenant="B", chunk_ids=["cB"], hops=2))


def test_mcp_client_can_search_a_tenants_graph(seeded):
    # Drive the tool through an actual MCP client session.
    async def run():
        async with connect(mcp_server.mcp) as session:
            await session.initialize()
            result = await session.call_tool(
                "retrieve", {"tenant": "A", "chunk_ids": ["cA"], "hops": 2})
            return result

    result = asyncio.run(run())
    assert not result.isError
    # facts come back as structured content (or JSON text); accept either form.
    facts = getattr(result, "structuredContent", None)
    if isinstance(facts, dict):
        facts = facts.get("result", facts.get("facts"))
    if facts is None:
        facts = json.loads(result.content[0].text)
    blob = json.dumps(facts).lower()
    assert "alpha co" in blob and "bravo co" not in blob
