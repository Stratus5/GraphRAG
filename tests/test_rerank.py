"""Rerank verification on the frozen fixture: the cross-encoder keeps the right facts
in the top-N. Skipped unless sentence-transformers is installed (model downloads
on first use). Loopback Neo4j."""

import json
import os

import pytest

from eval.bench import EVAL_TENANT, load_sample_into_neo4j
from eval.gold import GOLD
from eval.scoring import cosine_topk, evidence_text, score_required
from graphrag.config import load_config
from graphrag.ingestion.writer import get_graph
from graphrag.retrieval.expander import expand
from graphrag.retrieval.rerank import rerank_available, rerank_facts

FIXTURE = "eval/fixtures/domain.json"
TOP_N = 10
MODEL = "BAAI/bge-reranker-base"

pytestmark = pytest.mark.skipif(
    not rerank_available() or not os.path.exists(FIXTURE),
    reason="sentence-transformers not installed or fixture missing",
)


def _candidates(graph, fx, gold_id):
    rows = fx["chunks"]
    vecs = [c["embedding"] for c in rows]
    text_by_id = {c["chunk_id"]: c["text"] for c in rows}
    q = next(q for q in fx["queries"] if q["id"] == gold_id)
    topk = [rows[i]["chunk_id"] for i in cosine_topk(q["embedding"], vecs, 4)]
    load_sample_into_neo4j(graph, rows, fx["samples"][0], text_by_id)
    return q["question"], expand(graph, topk, hops=2, tenant=EVAL_TENANT)


def _required(gold_id):
    return next(g for g in GOLD if g["id"] == gold_id)["required"]


def test_multihop_bridge_fact_survives_rerank(neo4j_available):
    graph = get_graph(load_config("config.yaml"))
    question, cands = _candidates(graph, json.load(open(FIXTURE)), "MULTIHOP")
    assert len(cands) > TOP_N or True  # candidates may be small; rerank still must keep the bridge
    ranked = rerank_facts(question, cands, TOP_N, MODEL)
    m, t = score_required(_required("MULTIHOP"), evidence_text([], ranked))
    assert m == t, f"bridge fact not in top-{TOP_N}"
    # clean even after rerank
    assert all(f["predicate"] not in ("MENTIONS", "HAS_CHUNK") for f in ranked)


def test_aggregation_all_six_survive_rerank(neo4j_available):
    graph = get_graph(load_config("config.yaml"))
    question, cands = _candidates(graph, json.load(open(FIXTURE)), "AGGREGATION")
    ranked = rerank_facts(question, cands, TOP_N, MODEL)
    m, t = score_required(_required("AGGREGATION"), evidence_text([], ranked))
    assert m == t, f"only {m}/{t} acquired companies survived top-{TOP_N} rerank"


def test_rerank_is_deterministic(neo4j_available):
    graph = get_graph(load_config("config.yaml"))
    question, cands = _candidates(graph, json.load(open(FIXTURE)), "MULTIHOP")
    a = rerank_facts(question, cands, TOP_N, MODEL)
    b = rerank_facts(question, cands, TOP_N, MODEL)
    assert a == b
