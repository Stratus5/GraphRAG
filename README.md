# GraphRAG (LangChain + Neo4j)

Local GraphRAG demo. See <a href="ARCHITECTURE.md" target="_blank" rel="noopener noreferrer"><code>ARCHITECTURE.md</code></a> for the full design.

## Objective

Turn a folder of documents into a **queryable knowledge graph** and answer
natural-language questions grounded in it, with source citations.

Ingestion does more than embed text: it uses an LLM to extract **entities and the
relationships between them** (e.g. `Jane Doe -[:FOUNDED]-> Acme Corp`) and stores them
in Neo4j alongside the embedded text chunks. At query time it combines two retrieval
modes:

1. **Vector search** — find the chunks most semantically similar to the question.
2. **Graph expansion** — from the entities mentioned in those chunks, traverse the
   graph N hops to pull in related facts.

Both the passages and the structured facts become context for the LLM's answer.

## Why this beats plain vector search

Plain vector RAG retrieves the top-k chunks by similarity and hopes the answer sits
inside them. That breaks down whenever the answer requires **connecting information
that isn't co-located in a single chunk**:

| Question type | Plain vector search | GraphRAG |
|---------------|--------------------|----------|
| Fact stated in one passage | ✅ Works | ✅ Works |
| **Multi-hop** ("Who is the CTO of the company Jane founded?") | ❌ Needs two facts that rarely share a chunk | ✅ Graph traversal links them |
| **Aggregation** ("List every company Acme acquired") | ❌ Misses any chunk that falls outside top-k | ✅ Follows all `:ACQUIRED` edges from the entity |
| **Disambiguation** (same name, different entities) | ❌ Blends similar text | ✅ Distinct graph nodes |
| Explainability | Chunk text only | Explicit `subject → predicate → object` facts + citations |

Key advantages:

- **Relationships are first-class.** Connections are stored as graph edges, so answers
  can follow them deterministically instead of relying on two related facts happening to
  land in the same retrieved chunk.
- **Multi-hop reasoning.** `--hops` controls how far to traverse: `0` is chunks-only
  (plain RAG), `1` adds direct neighbors, `2` adds friends-of-friends.
- **Higher recall on connected facts.** Graph expansion surfaces relevant facts even when
  their source text never ranked in the top-k by similarity.
- **Grounded and auditable.** Context includes both source passages and explicit
  `subject → predicate → object` triples, and the model is instructed to cite sources and
  say "I don't know" when the answer isn't present.

It still degrades gracefully: if no graph facts are found, it answers from the chunks
alone — i.e. no worse than ordinary vector RAG.

## Quickstart
1. `cp .env.example .env` and fill in secrets.
2. Start Neo4j + Weaviate:
   - `docker compose up -d` (or `podman compose up -d`) — starts both stores, **or**
   - `./scripts/neo4j-up.sh` — plain-podman fallback (Neo4j only) when `podman compose` is
     unavailable (e.g. broken nested podman inside a toolbox). Stop with
     `./scripts/neo4j-down.sh`.
3. `pip install -e ".[openai,vector,dev]"`  (`vector` installs `weaviate-client>=4`)
4. `graphrag ingest sample_data/` — builds the Neo4j knowledge graph **and** the Weaviate
   vector index.
5. `graphrag query "Who founded the company?"` — Weaviate vector search → graph expansion →
   grounded answer.

Both stores bind to loopback. Neo4j: browser at http://localhost:7474, bolt at
`bolt://localhost:7687`. Weaviate: HTTP at http://localhost:8080.

## Demo

**Try it now — no setup:** <a href="https://graphrag.stratus5.net" target="_blank" rel="noopener noreferrer"><strong>graphrag.stratus5.net</strong></a> — a hosted
instance you can experience and play with straight in the browser.

To run it locally:

```bash
./demos/start.sh
```

Opens the demo SPA at **http://127.0.0.1:8800**. Three tabs: **Read** (watch each document get
parsed into entities + relationships and drawn onto the map), **Ask** (pick a question and watch
the answering facts light up across the graph, answer entities in yellow), and **Explore** (click
any entity to re-centre the graph on it). The Ask tab has two answer modes:

- **Curated** — answers driven by hand-authored, precision graph queries; no gateway key
  needed. Works offline.
- **Live** — the real retrieval pipeline: Weaviate vector search → N-hop graph expansion →
  cross-encoder reranking. The answer subgraph is highlighted, and facts recovered by graph
  expansion beyond the vector hits are labelled **graph-only** — the whole point of GraphRAG,
  made visible. Requires `OPENAI_BASE_URL` and `OPENAI_API_KEY` in `.env`.

The toggle in the UI switches between modes. "Live" will show as unavailable if the gateway
key is missing or Weaviate is empty.

## Tests
- Unit tests (no external services): `.venv/bin/python -m pytest -v`
- End-to-end integration test (needs Neo4j + an exported `OPENAI_API_KEY`):
  ```bash
  export OPENAI_API_KEY=sk-...
  ./scripts/run-integration-test.sh
  ```
  The runner starts Neo4j if needed, runs `tests/test_integration.py`, and then
  verifies the graph-expansion path is populated (Chunk→entity `:MENTIONS` edges),
  confirming real GraphRAG behavior rather than vector-only retrieval.
