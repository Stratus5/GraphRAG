"""Local demo server (loopback, no auth, no gateway). NOT the production surface
(that's graphrag/api.py behind mTLS). Serves the single-page app and a small API
over the hand-authored demo graph (see demos/scenario.py).
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from demos import scenario
from demos.load import main as load_demo_graph
from graphrag.config import load_config
from graphrag.ingestion.writer import get_graph

TENANT = "demo"
STATIC = Path(__file__).parent / "static"

cfg = load_config("config.yaml")
graph = get_graph(cfg)
# Self-load if the graph is missing (a test run or fresh DB may have wiped it),
# so the server is never serving an empty graph.
if not graph.query("MATCH (e:__Entity__ {tenant: $t}) RETURN 1 AS x LIMIT 1", {"t": TENANT}):
    load_demo_graph()
_Q = {q["id"]: q for q in scenario.QUESTIONS}

app = FastAPI(title="graphrag demos")


@app.middleware("http")
async def _no_cache(request, call_next):
    # Local demo: never let the browser cache the SPA, or edits won't show up.
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _edge(s, p, o, pct):
    label = p if pct is None else f"{p} {pct}%"
    return {"source": s, "predicate": p, "target": o, "label": label}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/graph")
def api_graph():
    rows = graph.query(
        """
        MATCH (a:__Entity__ {tenant: $t})-[r]->(b:__Entity__ {tenant: $t})
        RETURN a.id AS s, a.type AS st, type(r) AS p, b.id AS o, b.type AS ot, r.pct AS pct
        """, {"t": TENANT})
    nodes = {}
    edges = []
    for r in rows:
        nodes.setdefault(r["s"], r["st"] or "Entity")
        nodes.setdefault(r["o"], r["ot"] or "Entity")
        edges.append(_edge(r["s"], r["p"], r["o"], r["pct"]))
    return {"nodes": [{"id": k, "type": v} for k, v in nodes.items()], "edges": edges}


@app.get("/api/read-steps")
def api_read_steps():
    """Per-document: the text to type out, plus the nodes/edges extracted from it."""
    text_by_id = {c["chunk_id"]: c["text"] for c in scenario.CHUNKS}
    docs = []
    for gd in scenario.GRAPH[:len(scenario.COMPANIES)]:
        docs.append({
            "source": gd["source"],
            "text": text_by_id[gd["source_chunk_id"]],
            "nodes": [{"id": n["id"], "type": n["type"]} for n in gd["nodes"]],
            "edges": [{"source": r["source"]["id"], "target": r["target"]["id"],
                       "predicate": r["type"], "pct": r["properties"].get("pct")}
                      for r in gd["relationships"]],
        })
    return {"documents": docs}


@app.get("/api/questions")
def api_questions():
    return [{"id": q["id"], "question": q["question"]} for q in scenario.QUESTIONS]


# Each question is answered by a precise graph query (entity walk / property
# filter) so the answer subgraph is exactly the relevant facts, not a 2-hop blob.
QUERIES = {
    "FOUNDER_CO":
        "MATCH (f:__Entity__ {tenant:$t, id:'Ada Whitfield'})-[:FOUNDED]->(c:__Entity__ {tenant:$t}) "
        "RETURN f.id AS subject, 'FOUNDED' AS predicate, c.id AS object, null AS pct ORDER BY c.id",
    "VC_PORT":
        "MATCH (v:__Entity__ {tenant:$t, id:'Northwind Capital'})-[r:INVESTED_IN]->(c:__Entity__ {tenant:$t}) "
        "RETURN v.id AS subject, 'INVESTED_IN' AS predicate, c.id AS object, r.pct AS pct ORDER BY r.pct DESC",
    "BOTH_VC":
        "MATCH (c:__Entity__ {tenant:$t})<-[r:INVESTED_IN]-(v:__Entity__ {tenant:$t}) "
        "WITH c, collect({v:v.id, pct:r.pct}) AS inv WHERE size(inv) >= 2 "
        "UNWIND inv AS i RETURN i.v AS subject, 'INVESTED_IN' AS predicate, c.id AS object, i.pct AS pct ORDER BY c.id",
    "SHARED_CTO":
        "MATCH (p:__Entity__ {tenant:$t, id:'Maya Chen'})-[:CTO_OF]->(c:__Entity__ {tenant:$t}) "
        "RETURN p.id AS subject, 'CTO_OF' AS predicate, c.id AS object, null AS pct ORDER BY c.id",
    "CO_TEAM":
        "MATCH (x:__Entity__ {tenant:$t})-[r]->(c:__Entity__ {tenant:$t, id:'Vantage Payments'}) "
        "RETURN x.id AS subject, type(r) AS predicate, c.id AS object, r.pct AS pct ORDER BY predicate",
    "MAJORITY":
        "MATCH (v:__Entity__ {tenant:$t})-[r:INVESTED_IN]->(c:__Entity__ {tenant:$t}) WHERE r.pct > 50 "
        "RETURN v.id AS subject, 'INVESTED_IN' AS predicate, c.id AS object, r.pct AS pct ORDER BY v.id, r.pct DESC",
}


class Ask(BaseModel):
    id: str


@app.post("/api/ask")
def api_ask(a: Ask):
    q = _Q[a.id]
    rows = graph.query(QUERIES[a.id], {"t": TENANT})
    facts = [{"subject": r["subject"], "predicate": r["predicate"], "object": r["object"],
              "pct": r["pct"]} for r in rows]
    return {"question": q["question"], "facts": facts, "answer": q["answer"], "sources": []}
