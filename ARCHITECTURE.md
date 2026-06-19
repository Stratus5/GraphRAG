# GraphRAG — Architecture & Design

A modular, config-driven **knowledge-graph RAG** system built on LangChain and Neo4j.
It ingests documents into a knowledge graph (entities + relationships + embedded text
chunks), then answers questions using **hybrid retrieval**: dense vector search over
chunks combined with structured graph expansion over extracted entities.

---

## 1. Overview

GraphRAG turns a folder of documents into a queryable knowledge graph and answers
natural-language questions grounded in that graph, with source citations.

Two flows:

- **Ingestion** — `load → chunk → extract (LLM) → embed → write to Neo4j → link chunks to entities`
- **Retrieval** — `embed question → vector search → graph expand → assemble context → LLM answer`

Design goals:

- **Config-driven** — providers, chunking, and the extraction schema are all set in `config.yaml`; no code changes to retarget a domain.
- **Provider-agnostic** — LLM/embeddings SDK imports are isolated behind a factory.
- **Resilient** — per-file and per-chunk failure isolation, retries with backoff, idempotent writes.
- **Simple stack** — Neo4j serves as both graph store and vector index; no separate vector DB.

---

## 2. Technology Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python ≥ 3.11 | LangChain ecosystem |
| Orchestration | LangChain 0.3.x (+ community, experimental) | Unified LLM/embeddings abstractions, `LLMGraphTransformer` |
| Graph + vector store | Neo4j ≥ 5.20 (`langchain-neo4j`) | Native vector index + Cypher traversal in one engine |
| LLM / embeddings | OpenAI (pluggable) | Default provider; isolated behind `providers.py` |
| CLI | Typer | Decorator-based commands, auto `--help` |
| Config | YAML + `.env` (dotenv) | Human-readable, secrets out of source |
| Resilience | Tenacity | Retry with exponential backoff |
| UX | Rich | Ingestion progress bars |

---

## 3. Module Map

```
graphrag/
├── cli.py                  # Typer entry point: `ingest`, `query`
├── config.py               # Typed config dataclasses + load_config()
├── providers.py            # get_chat_model() / get_embeddings() factories
├── ingestion/
│   ├── loaders.py          # load_folder(): .txt/.md/.pdf → [Document]
│   ├── chunker.py          # chunk_documents(): split + stable SHA1 IDs
│   ├── extractor.py        # build_transformer() / extract_graph(): text → triples
│   ├── writer.py           # Neo4j persistence + vector index + chunk↔entity linking
│   └── pipeline.py         # ingest(): orchestrates the 7 stages
└── retrieval/
    ├── vector.py           # search(): Neo4j vector index query
    ├── expander.py         # build_expansion_query() / expand(): N-hop traversal
    ├── qa.py               # build_context() / answer(): prompt + LLM
    └── pipeline.py         # query(): orchestrates search → expand → answer
```

Separation of concerns is strict: each module does one stage, and the two `pipeline.py`
files are the only places that wire stages together.

---

## 4. Configuration

`config.yaml` (runtime, version-controlled):

```yaml
llm:
  provider: openai
  model: gpt-4.1-nano
embeddings:
  provider: openai
  model: text-embedding-3-small
chunking:
  size: 1000          # chars per chunk
  overlap: 200        # char overlap between chunks
schema:
  allowed_nodes: []          # empty = auto-derive; e.g. [Person, Company]
  allowed_relationships: []  # empty = auto-derive; e.g. [FOUNDED, ACQUIRED]
```

`.env` (secrets, **not** committed):

```bash
OPENAI_API_KEY=sk-...
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
```

`config.py` loads the YAML and overlays `NEO4J_*` from the environment into typed
dataclasses (`Config`, `ProviderConfig`, `ChunkingConfig`, `SchemaConfig`, `Neo4jConfig`).

> **Note:** the OpenAI key must be present in the environment when the LangChain OpenAI
> clients are constructed — exporting it after import does not help. Use `.env` / a real
> shell export before running.

---

## 5. Ingestion Pipeline

`ingest(cfg, folder, on_progress)` runs seven stages, reporting progress via a callback
`(stage: str, current: int, total: int)` so the CLI can render a Rich progress bar.

```
folder/                      graphrag ingest <folder>
  │
  ▼ 1. loaders.load_folder()           .txt/.md/.pdf → [Document]   (per-file errors skipped)
  ▼ 2. chunker.chunk_documents()       split + stable chunk_id      [Document] × M
  ▼ 3. extractor.build_transformer()   schema-aware LLMGraphTransformer
  ▼ 4. extractor.extract_graph()       per-chunk LLM extraction     [GraphDocument]
  │        (retry w/ backoff, failures isolated + counted)
  ▼ 5. writer.write_chunks()           embed text, MERGE :Chunk, CREATE vector index
  ▼ 6. writer.write_graph_documents()  MERGE entities + relationships (baseEntityLabel,
  │                                     include_source=True)
  ▼ 7. writer.link_chunks_to_entities()  connect :Chunk →[:MENTIONS]→ entities
  │
  ▼ returns {documents, chunks, graph_documents, extraction_failures}
```

Key design points:

- **Stable chunk IDs** — `chunk_id = SHA1(f"{source}:{index}:{content}")`, also copied to
  `metadata["id"]` so `langchain-neo4j`'s source nodes align with our `:Chunk` nodes.
  This makes re-ingestion idempotent (all writes are `MERGE`, never `CREATE`).
- **Per-chunk extraction** — each chunk is extracted independently. A chunk that fails
  (after retries) is logged and counted in `extraction_failures`; ingestion continues.
- **Retry with backoff** — `_convert` is wrapped in Tenacity
  (`stop_after_attempt(3)`, `wait_exponential(multiplier=1, max=10)`) to ride out transient
  API errors and rate limits.

### 5.1 The chunk → entity linkage (critical correctness detail)

`write_graph_documents` (via `langchain-neo4j`) creates entities and attaches them to its
**own** source `:Document` nodes keyed by `id` (our `chunk_id`). Separately, `write_chunks`
creates our `:Chunk` nodes. Without an explicit join, the embedded chunks and the extracted
entities live in **disjoint subgraphs** — vector search finds chunks, but graph expansion
finds nothing, silently degrading answers to plain RAG.

`link_chunks_to_entities()` repairs this by matching on the shared key and adding the edge:

```cypher
MATCH (src:Document)-[:MENTIONS]->(e)
WHERE src.id IS NOT NULL
MATCH (c:Chunk {chunk_id: src.id})
MERGE (c)-[:MENTIONS]->(e)
```

This step is what makes hybrid retrieval actually hybrid — keep it in the pipeline.

---

## 6. Graph Schema

```
(:Document {source})
   └─[:HAS_CHUNK]──▶ (:Chunk {chunk_id, text, embedding})
                        └─[:MENTIONS]──▶ (:__Entity__ {id, …})
                                            ├─[:FOUNDED]────▶ (:__Entity__)
                                            ├─[:ACQUIRED]───▶ (:__Entity__)
                                            ├─[:LOCATED_IN]─▶ (:__Entity__)
                                            └─[:<REL_TYPE>]─▶ (:__Entity__)
```

| Node | Labels | Key properties | Role |
|------|--------|----------------|------|
| Document | `:Document` | `source` | Provenance root (file path) |
| Chunk | `:Chunk` | `chunk_id`, `text`, `embedding` | Vector-searchable text unit |
| Entity | `:__Entity__` + domain label | `id`, LLM-derived props | Graph node; `__Entity__` base label enables uniform queries |

Vector index:

```cypher
CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: $dims,
                       `vector.similarity_function`: 'cosine'}}
```

Dimensions follow the embedding model (1536 for `text-embedding-3-small`); similarity is cosine.

### 6.1 Generic vs. Domain schema

The single switch is the `schema` block in `config.yaml`, passed straight into
`LLMGraphTransformer(allowed_nodes=…, allowed_relationships=…)`.

| Mode | Config | Behavior | Trade-off |
|------|--------|----------|-----------|
| **Generic** | empty lists | LLM invents node/rel types per chunk | Works on any domain, but ad-hoc inconsistent types (`FOUNDED_BY`, `CREATED`, `STARTED`…) make traversal unpredictable |
| **Domain** | populated lists | LLM constrained to your vocabulary | Clean, consistent, predictable graph; requires schema design up front |

See `docs/domain-schema-walkthrough.md` for the reset-and-re-ingest workflow.

---

## 7. Retrieval Pipeline

`query(cfg, question, k=4, hops=1)`:

```
"Who founded Acme Corp?"          graphrag query "<question>" [--k 4] [--hops 1]
  │
  ▼ embed question                 providers.get_embeddings()
  ▼ vector.search(k)               db.index.vector.queryNodes('chunk_embedding', k, emb)
  │      → top-k chunks {chunk_id, text, source, score}
  ▼ expander.expand(chunk_ids, hops)
  │      (:Chunk)-[:MENTIONS]->(e)-[r*1..hops]-(neighbor)  → facts {subject, predicate, object}  (LIMIT 100)
  ▼ qa.build_context(chunks, facts)
  │      ## Passages  [source] text …
  │      ## Known facts  - subject PREDICATE object …
  ▼ qa.answer(llm, question, chunks, facts)   PROMPT | llm
  │
  ▼ grounded answer with source citations
```

- **Hybrid retrieval** — dense (chunk vectors) + structured (entity neighborhood) context.
- **Configurable hops** — `--hops 0` is chunks-only; `1` adds direct neighbors; `2` adds
  friends-of-friends. Variable-length Cypher with `LIMIT 100` prevents runaway expansion.
- **Graceful degradation** — if expansion yields no facts, the answer still comes from chunks.
- **Grounding** — the system prompt instructs the model to answer strictly from context,
  cite source files, and say "I don't know" when the answer is absent.

---

## 8. CLI

Entry point `graphrag = graphrag.cli:app`:

```bash
graphrag ingest <folder> [--config config.yaml]
graphrag query  "<question>" [--config config.yaml] [--k 4] [--hops 1]
```

Example:

```bash
graphrag ingest sample_data/
# [done] 1 docs  4 chunks  12 graph-docs  failures=0

graphrag query "Who founded Acme Corp?"
# Acme Corp was founded by Jane Doe and John Smith in 2010. (sample_data/founders.txt)
```

---

## 9. Resilience Summary

| Concern | Mechanism | Location |
|---------|-----------|----------|
| Bad input file | Per-file try/except, log + skip | `loaders.py` |
| LLM extraction failure | Per-chunk isolation, count failures | `extractor.py` |
| Transient API errors | Tenacity retry, exponential backoff (≤3) | `extractor.py` |
| Duplicate writes | `MERGE` everywhere + stable IDs → idempotent | `chunker.py`, `writer.py` |
| Disjoint subgraphs | Explicit chunk↔entity linking step | `writer.py` |
| Missing facts at query | Fall back to chunk-only context | `retrieval/pipeline.py` |

---

## 10. External Services

| Service | Purpose | Endpoint / Access |
|---------|---------|-------------------|
| Neo4j | Graph store + vector index | `bolt://localhost:7687`, browser at `:7474` (run via `./scripts/neo4j-up.sh` / Podman) |
| OpenAI | LLM + embeddings | API key via `.env` (`OPENAI_API_KEY`) |

---

## 11. Testing

- **Unit** (no services, ~seconds): `test_config`, `test_chunker`, `test_extractor`,
  `test_expander`, `test_qa`, `test_cli` — pure logic and string builders, mocked LLM.
- **Integration** (live Neo4j + `OPENAI_API_KEY`): `test_integration` — clears the graph,
  ingests `sample_data/`, asserts stats, queries, and checks the answer.

```bash
pytest -v                         # unit
./scripts/run-integration-test.sh # integration (needs Neo4j + key)
```

---

## 12. Extension Points

All fit within current interfaces — no breaking changes required:

1. **More providers** — add branches in `providers.py` (Anthropic, Azure, Ollama/local).
2. **Entity deduplication** — merge `Acme Corp` / `Acme` into one node post-ingest.
3. **Typed relationship constraints** — `(Person, FOUNDED, Company)` triples vs. flat strings.
4. **Async / parallel extraction** — fan out per-chunk LLM calls.
5. **HTTP API** — FastAPI wrapper over `ingest` / `query`.
6. **Community detection** — cluster entities and summarize per community (GraphRAG-style).
