"""Deterministic frozen-fixture benchmark (Neo4j only, no gateway, no answer-LLM).

    set -a && . ./.env && set +a   # needs NEO4J_* only
    .venv/bin/python -m eval.bench [--k 4] [--hops 2] [--mode generic|domain]

Replays recorded embeddings (in-process cosine) for vector ranking and replays
each frozen extraction sample into loopback Neo4j, then exercises the REAL
expander. Verdict is retrieval-presence (see eval/gold.py), so two consecutive
runs are byte-identical (Phase 0.2). For MULTIHOP it also asserts the 0.3 gate:
the Acme-naming anchor chunk is IN top-k and the bridging CTO chunk is OUT.
"""

import argparse
import glob
import json
import os

from eval.gold import GOLD
from eval.graphdoc_io import deserialize_graph_docs
from eval.scoring import bridge_predicates, cosine_topk, evidence_text, score_required
from graphrag.config import load_config
from graphrag.ingestion.writer import CHUNK_WRITE, get_graph, link_chunks_to_entities
from graphrag.retrieval.expander import expand

COUNT_CHUNK_MENTIONS = "MATCH (:Chunk)-[m:MENTIONS]->() RETURN count(m) AS n"

# Single-tenant eval: load via the langchain path (shape Phase 0 validated) then
# tag everything one tenant. Post-write re-tag is safe here precisely because it's
# single-tenant + clean-slate + no concurrency — the race that rules it out on the
# service path can't occur. Keeps tenant mandatory in expand without an escape hatch.
EVAL_TENANT = "eval"


def load_sample_into_neo4j(graph, chunk_rows, sample, text_by_id):
    graph.query("MATCH (n) DETACH DELETE n")
    graph.query(CHUNK_WRITE, {"rows": [
        {"source": c["source"], "chunk_id": c["chunk_id"], "text": c["text"]}
        for c in chunk_rows
    ], "tenant": EVAL_TENANT})
    graph.add_graph_documents(
        deserialize_graph_docs(sample, text_by_id),
        baseEntityLabel=True, include_source=True,
    )
    link_chunks_to_entities(graph)
    graph.query("MATCH (n) WHERE n.tenant IS NULL SET n.tenant = $tenant",
                {"tenant": EVAL_TENANT})
    n = graph.query(COUNT_CHUNK_MENTIONS)[0]["n"]
    if n == 0:
        raise RuntimeError("0 :Chunk-[:MENTIONS]->entity edges after load "
                           "(metadata['id']=chunk_id lost?)")
    return n


def run_fixture(graph, path, k, hops):
    fx = json.load(open(path))
    mode = fx["mode"]
    chunk_rows = fx["chunks"]
    chunk_vecs = [c["embedding"] for c in chunk_rows]
    text_by_id = {c["chunk_id"]: c["text"] for c in chunk_rows}
    src_by_id = {c["chunk_id"]: c["source"] for c in chunk_rows}
    q_by_id = {q["id"]: q for q in fx["queries"]}

    lines = [f"\n===== MODE: {mode}  (k={k}, hops={hops}, samples={len(fx['samples'])}) ====="]

    for g in GOLD:
        q = q_by_id[g["id"]]
        topk_idx = cosine_topk(q["embedding"], chunk_vecs, k)
        topk = [chunk_rows[i]["chunk_id"] for i in topk_idx]
        topk_src = [src_by_id[cid] for cid in topk]
        lines.append(f"\n[{g['id']}] {g['question']}")
        lines.append(f"  top-{k} sources: {topk_src}")

        # 0.3 gate: bridging chunk must be outside top-k, anchor inside.
        if "bridge_source" in g:
            anchor_in = g["anchor_source"] in topk_src
            bridge_out = g["bridge_source"] not in topk_src
            ok = anchor_in and bridge_out
            lines.append(f"  GATE anchor({g['anchor_source']})_in_topk={anchor_in} "
                         f"bridge({g['bridge_source']})_out_of_topk={bridge_out} "
                         f"-> {'OK' if ok else 'FAIL'}")

        # vector-only (hops0): sample-independent.
        ev0 = evidence_text([text_by_id[cid] for cid in topk], [])
        m0, t0 = score_required(g["required"], ev0)
        v0 = "PASS" if m0 == t0 else f"MISS({m0}/{t0})"
        lines.append(f"  vector-only          : {v0}")

        # graph (hops>0): one verdict per frozen extraction sample.
        passes = 0
        details = []
        pred_sets = []
        unclean = 0
        for sample in fx["samples"]:
            load_sample_into_neo4j(graph, chunk_rows, sample, text_by_id)
            facts = expand(graph, topk, hops=hops, tenant=EVAL_TENANT)
            unclean += sum(1 for f in facts
                           if f["subject"] is None or f["object"] is None
                           or f["predicate"] in ("MENTIONS", "HAS_CHUNK"))
            ev = evidence_text([text_by_id[cid] for cid in topk], facts)
            m, t = score_required(g["required"], ev)
            details.append(f"{m}/{t}")
            if m == t:
                passes += 1
            pred_sets.append(bridge_predicates(facts, g["required"]))
        n = len(fx["samples"])
        lines.append(f"  graph h{hops} pass-rate : {passes}/{n}   per-sample={details}")
        lines.append(f"  facts clean (no MENTIONS/None): {'YES' if unclean == 0 else f'NO ({unclean})'}")
        # Schema-shape separator (spec #3): which edge types reach the answer entity.
        if "bridge_source" in g:
            lines.append(f"  bridge predicates    : {pred_sets}")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--mode", default=None, help="generic|domain (default: all fixtures)")
    args = ap.parse_args()

    cfg = load_config("config.yaml")
    graph = get_graph(cfg)

    if args.mode:
        paths = [f"eval/fixtures/{args.mode}.json"]
    else:
        paths = sorted(glob.glob("eval/fixtures/*.json"))
    if not paths or not all(os.path.exists(p) for p in paths):
        raise SystemExit("no fixtures found — run `python -m eval.record` first")

    out = [run_fixture(graph, p, args.k, args.hops) for p in paths]
    print("\n".join(out))


if __name__ == "__main__":
    main()
