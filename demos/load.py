"""Load the hand-authored demo scenario into Neo4j under tenant 'demo'
(offline, no gateway) via the real tenant graph write path.
"""

from demos.scenario import CHUNKS, GRAPH
from eval.graphdoc_io import deserialize_graph_docs
from graphrag.config import load_config
from graphrag.ingestion.pipeline import _documents_from_chunks
from graphrag.ingestion.writer import (
    create_constraints,
    get_graph,
    write_chunks,
    write_graph_tenant,
)

TENANT = "demo"


def main():
    cfg = load_config("config.yaml")
    graph = get_graph(cfg)

    graph.query("MATCH (n {tenant: $t}) DETACH DELETE n", {"t": TENANT})
    for c in graph.query("SHOW CONSTRAINTS YIELD name RETURN name"):
        graph.query(f"DROP CONSTRAINT {c['name']} IF EXISTS")
    create_constraints(graph)

    text_by_id = {c["chunk_id"]: c["text"] for c in CHUNKS}
    rows = [{"chunk_id": c["chunk_id"], "text": c["text"], "source": c["source"]} for c in CHUNKS]
    write_chunks(graph, _documents_from_chunks(rows), TENANT)
    write_graph_tenant(graph, deserialize_graph_docs(GRAPH, text_by_id), TENANT)

    n = graph.query("MATCH (e:__Entity__ {tenant: $t}) RETURN count(e) AS n", {"t": TENANT})[0]["n"]
    r = graph.query("MATCH (:__Entity__ {tenant: $t})-[x]->(:__Entity__ {tenant: $t}) "
                    "RETURN count(x) AS n", {"t": TENANT})[0]["n"]
    print(f"[demos] loaded {len(rows)} chunks, {n} entities, {r} relationships under '{TENANT}'")


if __name__ == "__main__":
    main()
