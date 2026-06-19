"""Serialize / reconstruct LLM-extracted graph documents for frozen fixtures.

The whole point of the frozen benchmark is that extraction (non-deterministic,
gateway-bound) happens once in record.py and is replayed deterministically in
bench.py. This module is the (de)serializer for that boundary.
"""

from langchain_community.graphs.graph_document import GraphDocument, Node, Relationship
from langchain_core.documents import Document


def serialize_graph_docs(graph_docs) -> list[dict]:
    out = []
    for gd in graph_docs:
        meta = gd.source.metadata
        out.append({
            "source_chunk_id": meta["id"],
            "source": meta.get("source", "unknown"),
            "nodes": [
                {"id": n.id, "type": n.type, "properties": n.properties}
                for n in gd.nodes
            ],
            "relationships": [
                {
                    "source": {"id": r.source.id, "type": r.source.type},
                    "target": {"id": r.target.id, "type": r.target.type},
                    "type": r.type,
                    "properties": r.properties,
                }
                for r in gd.relationships
            ],
        })
    return out


def deserialize_graph_docs(sample: list[dict], text_by_chunk_id: dict[str, str]) -> list[GraphDocument]:
    docs = []
    for gd in sample:
        cid = gd["source_chunk_id"]
        # metadata["id"]=chunk_id is mandatory: link_chunks_to_entities matches
        # :Chunk{chunk_id} against the langchain source :Document{id}. Drop it and
        # MENTIONS edges silently vanish and every graph case "fails retrieval".
        source = Document(
            page_content=text_by_chunk_id[cid],
            metadata={"id": cid, "source": gd["source"]},
        )
        nodes = [Node(id=n["id"], type=n["type"], properties=n["properties"]) for n in gd["nodes"]]
        rels = [
            Relationship(
                source=Node(id=r["source"]["id"], type=r["source"]["type"]),
                target=Node(id=r["target"]["id"], type=r["target"]["type"]),
                type=r["type"],
                properties=r["properties"],
            )
            for r in gd["relationships"]
        ]
        docs.append(GraphDocument(nodes=nodes, relationships=rels, source=source))
    return docs
