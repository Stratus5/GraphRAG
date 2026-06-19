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


from graphrag import vectorstore
from graphrag.providers import get_embeddings


def vectors_ready() -> bool:
    """True if the demo tenant has any vectors in Weaviate (and Weaviate is reachable)."""
    try:
        client = vectorstore.connect()
    except Exception:
        return False
    try:
        if not client.collections.exists(vectorstore.COLLECTION):
            return False
        hits = vectorstore.search(client, get_embeddings(load_config("config.yaml")),
                                  "ready check", k=1, tenant=TENANT)
        return bool(hits)
    except Exception:
        return False
    finally:
        client.close()


def build_vectors() -> int:
    """Embed scenario chunks into Weaviate under tenant 'demo'. Needs the gateway
    (OPENAI_BASE_URL/OPENAI_API_KEY). Returns count written (0 if it can't build)."""
    cfg = load_config("config.yaml")
    rows = [{"chunk_id": c["chunk_id"], "text": c["text"], "source": c["source"]}
            for c in CHUNKS]
    client = vectorstore.connect()
    try:
        n = vectorstore.build_index(client, get_embeddings(cfg), rows, TENANT)
    finally:
        client.close()
    print(f"[demos] built vector index: {n} chunks under '{TENANT}'")
    return n
