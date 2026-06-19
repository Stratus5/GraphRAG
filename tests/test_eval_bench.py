"""Integration: the frozen-fixture bench is deterministic (0.2) and the
multi-hop gate holds (0.3). Needs loopback Neo4j; skips otherwise."""

import os

import pytest

from eval.bench import run_fixture
from graphrag.config import load_config
from graphrag.ingestion.writer import get_graph

DOMAIN = "eval/fixtures/domain.json"

pytestmark = pytest.mark.skipif(
    not os.path.exists(DOMAIN), reason="fixtures not recorded (run eval.record)"
)


def test_bench_is_deterministic(neo4j_available):
    graph = get_graph(load_config("config.yaml"))
    a = run_fixture(graph, DOMAIN, k=4, hops=2)
    b = run_fixture(graph, DOMAIN, k=4, hops=2)
    assert a == b


def test_multihop_gate_and_lift(neo4j_available):
    graph = get_graph(load_config("config.yaml"))
    out = run_fixture(graph, DOMAIN, k=4, hops=2)
    # 0.3: bridging chunk outside top-k, anchor inside, vector-only fails retrieval.
    assert "bridge(maria_garcia.txt)_out_of_topk=True" in out
    assert "anchor(acme.txt)_in_topk=True" in out
    assert "vector-only          : MISS(0/1)" in out
    assert "graph h2 pass-rate : 3/3" in out
    # Aggregation lift (the validated clean win): vector 3/6, graph 6/6.
    assert "vector-only          : MISS(3/6)" in out
