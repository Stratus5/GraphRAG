"""Record extraction + embeddings to frozen JSON fixtures (gateway-bound).

Run once (needs OPENAI_API_KEY + OPENAI_BASE_URL pointing at the FC gateway):

    set -a && . ./.env && set +a
    .venv/bin/python -m eval.record [--samples N]

For every schema mode it embeds each chunk + each gold question once, and runs
extraction N times (default 3) to capture the extraction non-determinism that
finding #4 named. bench.py replays these without any network call.
"""

import argparse
import json

from eval.gold import CORPUS_DIR, GOLD, MODES
from eval.graphdoc_io import serialize_graph_docs
from graphrag.config import load_config
from graphrag.ingestion.chunker import chunk_documents
from graphrag.ingestion.extractor import build_transformer, extract_graph
from graphrag.ingestion.loaders import load_folder
from graphrag.providers import get_chat_model, get_embeddings

FIXTURE_DIR = "eval/fixtures"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3, help="extraction runs per mode")
    args = ap.parse_args()

    cfg = load_config("config.yaml")
    docs = load_folder(CORPUS_DIR)
    chunks = chunk_documents(docs, cfg.chunking.size, cfg.chunking.overlap)
    print(f"[record] {len(docs)} docs -> {len(chunks)} chunks")

    emb = get_embeddings(cfg)
    chunk_vecs = emb.embed_documents([c.page_content for c in chunks])
    chunk_rows = [
        {
            "chunk_id": c.metadata["chunk_id"],
            "source": c.metadata.get("source", "unknown").split("/")[-1],
            "text": c.page_content,
            "embedding": vec,
        }
        for c, vec in zip(chunks, chunk_vecs)
    ]
    query_rows = [
        {"id": g["id"], "question": g["question"], "embedding": emb.embed_query(g["question"])}
        for g in GOLD
    ]
    print(f"[record] embedded {len(chunk_rows)} chunks + {len(query_rows)} queries")

    llm = get_chat_model(cfg)
    for mode, schema in MODES.items():
        transformer = build_transformer(
            llm=llm,
            allowed_nodes=schema["allowed_nodes"],
            allowed_relationships=schema["allowed_relationships"],
        )
        samples = []
        for s in range(args.samples):
            graph_docs, failures = extract_graph(transformer, chunks)
            rels = sum(len(gd.relationships) for gd in graph_docs)
            print(f"[record:{mode}] sample {s+1}/{args.samples}: "
                  f"{len(graph_docs)} graph_docs, {rels} rels, {failures} fail")
            samples.append(serialize_graph_docs(graph_docs))

        path = f"{FIXTURE_DIR}/{mode}.json"
        with open(path, "w") as fh:
            json.dump({
                "mode": mode,
                "schema": schema,
                "chunks": chunk_rows,
                "queries": query_rows,
                "samples": samples,
            }, fh)
        print(f"[record:{mode}] wrote {path}")


if __name__ == "__main__":
    main()
