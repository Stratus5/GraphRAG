"""Phase 3.2/3.3: the HTTP surface. mTLS is terminated by nginx, which injects
X-SSL-Client-Verify + X-SSL-Client-DN; the app fails closed on them and on a CN
allow-list. Tenant stays in X-Tenant (the cert is a service identity, not a
tenant) and is trustworthy because only an allow-listed service can reach the
endpoint. Loopback Neo4j; no gateway."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport
from langchain_community.graphs.graph_document import GraphDocument, Node, Relationship
from langchain_core.documents import Document

from graphrag.api import create_app
from graphrag.config import load_config
from graphrag.ingestion.writer import (
    create_constraints,
    get_graph,
    write_chunks,
    write_graph_tenant,
)
from tests.conftest import reset_schema

ALLOWED_CN = "rag-worker"
MTLS = {"X-SSL-Client-Verify": "SUCCESS", "X-SSL-Client-DN": f"CN={ALLOWED_CN},OU=svc,O=fc"}


def _h(tenant, **extra):
    return {**MTLS, "X-Tenant": tenant, **extra}


def _write(graph, tenant, chunk_id, source, head, tail):
    write_chunks(graph, [Document(page_content="t",
                 metadata={"id": chunk_id, "chunk_id": chunk_id, "source": source})], tenant=tenant)
    h, t = Node(id=head, type="Company"), Node(id=tail, type="Company")
    write_graph_tenant(graph, [GraphDocument(
        nodes=[h, t], relationships=[Relationship(source=h, target=t, type="ACQUIRED")],
        source=Document(page_content="t", metadata={"id": chunk_id, "source": source}),
    )], tenant=tenant)


@pytest.fixture
def cfg(neo4j_available):
    cfg = load_config("config.yaml")
    g = get_graph(cfg)
    g.query("MATCH (n) DETACH DELETE n")
    reset_schema(g)
    create_constraints(g)
    _write(g, "A", "cA", "a.txt", "Acme Corp", "Alpha Co")
    _write(g, "B", "cB", "b.txt", "Acme Corp", "Bravo Co")
    g.close()
    return cfg


def _app(cfg):
    return create_app(cfg, allowed_clients={ALLOWED_CN})


def _ents(facts):
    return {f["object"] for f in facts} | {f["subject"] for f in facts}


# --- /health is open ----------------------------------------------------------
def test_health_is_open_without_mtls_headers(cfg):
    with TestClient(_app(cfg)) as client:
        r = client.get("/health")
        assert r.status_code == 200 and r.json() == {"status": "ok"}


# --- fail-closed mTLS enforcement (3.3) --------------------------------------
def test_missing_client_verify_is_403(cfg):
    with TestClient(_app(cfg)) as client:
        r = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2},
                        headers={"X-Tenant": "A"})  # no X-SSL-* at all
        assert r.status_code == 403


def test_no_headers_at_all_is_403_not_400(cfg):
    # The mTLS guard runs before the tenant check: an unauthenticated request
    # gets 403, never a 400 that would reveal the tenant-header requirement.
    with TestClient(_app(cfg)) as client:
        r = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2})
        assert r.status_code == 403


def test_client_verify_failed_is_403(cfg):
    with TestClient(_app(cfg)) as client:
        r = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2},
                        headers={"X-Tenant": "A", "X-SSL-Client-Verify": "FAILED",
                                 "X-SSL-Client-DN": f"CN={ALLOWED_CN}"})
        assert r.status_code == 403


def test_verified_but_non_allowlisted_cn_is_403(cfg):
    with TestClient(_app(cfg)) as client:
        r = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2},
                        headers={"X-Tenant": "A", "X-SSL-Client-Verify": "SUCCESS",
                                 "X-SSL-Client-DN": "CN=intruder,OU=svc"})
        assert r.status_code == 403


def test_empty_allowlist_rejects_all(cfg):
    # Misconfig (no GRAPHRAG_ALLOWED_CLIENTS) must fail closed even for a good cert.
    with TestClient(create_app(cfg, allowed_clients=set())) as client:
        r = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2}, headers=_h("A"))
        assert r.status_code == 403


def test_delete_and_ingest_also_guarded(cfg):
    with TestClient(_app(cfg)) as client:
        assert client.post("/delete", json={"source": "a.txt"},
                           headers={"X-Tenant": "A"}).status_code == 403
        assert client.post("/ingest", json={"chunks": []},
                           headers={"X-Tenant": "A"}).status_code == 403


# --- tenant model behind a verified client -----------------------------------
def test_retrieve_requires_tenant_header(cfg):
    with TestClient(_app(cfg)) as client:
        r = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2}, headers=MTLS)
        assert r.status_code == 400


def test_retrieve_is_tenant_scoped_at_http_boundary(cfg):
    with TestClient(_app(cfg)) as client:
        a = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2},
                        headers=_h("A")).json()["facts"]
        assert "Alpha Co" in _ents(a) and "Bravo Co" not in _ents(a)
        cross = client.post("/retrieve", json={"chunk_ids": ["cB"], "hops": 2},
                            headers=_h("A")).json()["facts"]
        assert cross == []


def test_delete_endpoint_is_tenant_scoped(cfg):
    with TestClient(_app(cfg)) as client:
        client.post("/delete", json={"source": "a.txt"}, headers=_h("A"))
        gone = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2},
                           headers=_h("A")).json()["facts"]
        assert gone == []
        b = client.post("/retrieve", json={"chunk_ids": ["cB"], "hops": 2},
                        headers=_h("B")).json()["facts"]
        assert "Bravo Co" in _ents(b)


def test_ingest_threads_tenant_through(cfg, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "graphrag.api.ingest_chunks",
        lambda c, tenant, chunks, graph=None: seen.update(tenant=tenant, n=len(chunks)) or {"ok": True})
    with TestClient(_app(cfg)) as client:
        r = client.post("/ingest",
                        json={"chunks": [{"chunk_id": "x", "text": "t", "source": "s"}]},
                        headers=_h("A"))
        assert r.status_code == 200
        assert seen == {"tenant": "A", "n": 1}


def test_ingest_reuses_pooled_driver(cfg, monkeypatch):
    # If the /ingest path opened its own driver, this get_graph would fire and 500.
    monkeypatch.setattr("graphrag.ingestion.pipeline.get_graph",
                        lambda c: (_ for _ in ()).throw(AssertionError("opened a new driver")))
    # Stub the LLM-bound bits so the write path runs offline against the pooled graph.
    monkeypatch.setattr("graphrag.ingestion.pipeline.get_chat_model", lambda c: None)
    monkeypatch.setattr("graphrag.ingestion.pipeline.build_transformer", lambda **k: None)
    monkeypatch.setattr("graphrag.ingestion.pipeline.extract_graph",
                        lambda t, docs, on_progress=None: ([], 0))
    with TestClient(_app(cfg)) as client:
        r = client.post("/ingest",
                        json={"chunks": [{"chunk_id": "x", "text": "t", "source": "s"}]},
                        headers=_h("A"))
        assert r.status_code == 200  # 500 here means a new driver was built


def test_rerank_failure_falls_back_to_deterministic(cfg, monkeypatch):
    # Package present but model load fails (fresh sidecar / no HF egress): must not 500.
    monkeypatch.setattr("graphrag.retrieval.rerank._model",
                        lambda name: (_ for _ in ()).throw(RuntimeError("model unavailable")))
    with TestClient(_app(cfg)) as client:
        with_q = client.post("/retrieve",
                             json={"chunk_ids": ["cA"], "hops": 2, "question": "who is cto?"},
                             headers=_h("A"))
        without_q = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": 2}, headers=_h("A"))
        assert with_q.status_code == 200
        assert "Alpha Co" in _ents(with_q.json()["facts"])
        # fell back to the deterministic expander order
        assert with_q.json()["facts"] == without_q.json()["facts"]


def test_hops_out_of_range_is_rejected(cfg):
    with TestClient(_app(cfg)) as client:
        for bad in (0, -1, 99):
            r = client.post("/retrieve", json={"chunk_ids": ["cA"], "hops": bad}, headers=_h("A"))
            assert r.status_code == 422


def test_concurrent_requests_do_not_serialize(cfg, monkeypatch):
    # 0.3s-sleeping handler, 10 at once: threadpooled ~0.3s, serialized ~3.0s.
    import time

    monkeypatch.setattr("graphrag.api.retrieve", lambda *a, **k: (time.sleep(0.3) or []))
    app = _app(cfg)

    async def run():
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            async def one():
                return await ac.post("/retrieve", json={"chunk_ids": ["x"], "hops": 1}, headers=_h("A"))
            t0 = time.perf_counter()
            await asyncio.gather(*[one() for _ in range(10)])
            return time.perf_counter() - t0

    assert asyncio.run(run()) < 1.5


def test_concurrent_requests_stay_isolated(cfg):
    app = _app(cfg)

    async def run():
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            async def one(tenant, cid, expect, forbid):
                r = await ac.post("/retrieve", json={"chunk_ids": [cid], "hops": 2}, headers=_h(tenant))
                ents = _ents(r.json()["facts"])
                return expect in ents and forbid not in ents
            tasks = ([one("A", "cA", "Alpha Co", "Bravo Co") for _ in range(15)] +
                     [one("B", "cB", "Bravo Co", "Alpha Co") for _ in range(15)])
            return await asyncio.gather(*tasks)

    assert all(asyncio.run(run()))
