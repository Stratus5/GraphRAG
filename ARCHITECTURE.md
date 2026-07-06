# GraphRAG — Architecture & Design

A modular, config-driven **knowledge-graph RAG** system built on LangChain and Neo4j.
It ingests documents into a knowledge graph (entities + relationships + embedded text
chunks), then answers questions using **hybrid retrieval**: dense vector search over
chunks combined with structured graph expansion over extracted entities.

---

## 1. Overview

GraphRAG turns a folder of documents into a queryable knowledge graph and answers
natural-language questions grounded in that graph, with source citations.

> **Live demo:** a hosted instance runs at **[graphrag.stratus5.net](https://graphrag.stratus5.net)** —
> the Read/Ask/Explore SPA with both Curated (precise graph queries) and Live (the real
> vector → expand → rerank pipeline) modes. See `demos/` and README for running it locally.

Two flows:

- **Ingestion** — `load → chunk → extract (LLM) → embed → write to Neo4j → link chunks to entities`
- **Retrieval** — `embed question → vector search → graph expand → assemble context → LLM answer`

Design goals:

- **Config-driven** — providers, chunking, and the extraction schema are all set in `config.yaml`; no code changes to retarget a domain.
- **Provider-agnostic** — LLM/embeddings SDK imports are isolated behind a factory.
- **Resilient** — per-file and per-chunk failure isolation, retries with backoff, idempotent writes.
- **Split store** — Neo4j is the graph store (entities + relationships + chunk anchors); Weaviate is the vector index. The service path is graph-only; vector search is a separate `graphrag/vectorstore.py` capability used by the CLI, demo, and eval but never by the mTLS service.

---

## 2. Technology Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python ≥ 3.11 | LangChain ecosystem |
| Orchestration | LangChain 0.3.x (+ community, experimental) | Unified LLM/embeddings abstractions, `LLMGraphTransformer` |
| Graph store | Neo4j ≥ 5.20 (`langchain-neo4j`) | Cypher traversal; entities, relationships, chunk anchors — no embeddings stored here |
| Vector store | Weaviate ≥ 1.x (`weaviate-client>=4`) | Tenant-scoped dense vector search (CLI/demo/eval path only) |
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
├── vectorstore.py          # Weaviate vector search — CLI/demo/eval only; NEVER imported by service path
├── api.py                  # FastAPI service (mTLS-gated, tenant-scoped, graph-only)
├── mcp_server.py           # MCP tool surface over the same service functions as api.py
├── ingestion/
│   ├── loaders.py          # load_folder(): .txt/.md/.pdf → [Document]
│   ├── chunker.py          # chunk_documents(): split + stable SHA1 IDs
│   ├── extractor.py        # build_transformer() / extract_graph(): text → triples
│   ├── writer.py           # Neo4j persistence (graph + chunk anchors; no embeddings stored)
│   └── pipeline.py         # ingest() (CLI/eval, builds graph + Weaviate index); ingest_chunks() (service, graph only)
└── retrieval/
    ├── expander.py         # build_expansion_query() / expand(): N-hop traversal
    ├── qa.py               # build_context() / answer(): prompt + LLM
    ├── rerank.py           # cross-encoder rerank (optional BGE)
    ├── service.py          # retrieve(): graph-only service retrieve (no vector layer)
    └── pipeline.py         # query(): CLI/eval orchestration (Weaviate search → expand → answer)
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
expander:
  max_degree: 50             # skip expansion through hub entities above this degree
  candidate_limit: 500       # deterministic fact budget from the expander (Cypher LIMIT)
  top_n: 10                  # facts kept after rerank
  rerank_model: BAAI/bge-reranker-base
```

`.env` (secrets, **not** committed):

```bash
OPENAI_API_KEY=sk-...
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
```

`config.py` loads the YAML and overlays `NEO4J_*` from the environment into typed
dataclasses (`Config`, `ProviderConfig`, `ChunkingConfig`, `SchemaConfig`,
`ExpanderConfig`, `Neo4jConfig`). Model names may carry an `fc:openai/…` gateway prefix.

> **Note:** the OpenAI key must be present in the environment when the LangChain OpenAI
> clients are constructed — exporting it after import does not help. Use `.env` / a real
> shell export before running.

---

## 5. Ingestion Pipeline

`ingest(cfg, folder, on_progress)` (CLI/eval path) runs these stages, reporting progress via a
callback `(stage: str, current: int, total: int)` so the CLI can render a Rich progress bar.

```
folder/                      graphrag ingest <folder>
  │
  ▼ 1. loaders.load_folder()           .txt/.md/.pdf → [Document]   (per-file errors skipped)
  ▼ 2. chunker.chunk_documents()       split + stable chunk_id      [Document] × M
  ▼ 3. extractor.build_transformer()   schema-aware LLMGraphTransformer
  ▼ 4. extractor.extract_graph()       per-chunk LLM extraction     [GraphDocument]
  │        (retry w/ backoff, failures isolated + counted)
  ▼ 5. writer.write_chunks()           MERGE :Chunk (text + chunk_id; no embedding stored)
  ▼ 6. writer.write_graph_tenant()     MERGE entities + relationships, :Chunk→[:MENTIONS]→entity
  │                                     (tenant-scoped; replaces langchain add_graph_documents)
  ▼ 7. vectorstore.build_index()       embed chunks, upsert into Weaviate "Chunk" collection
  │
  ▼ returns {documents, chunks, graph_documents, extraction_failures}
```

The service-path equivalent (`ingest_chunks`) runs only stages 4–6 (no loaders, no chunker,
no Weaviate write — the platform is the chunk authority and owns its own vector index).

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

**Primary path (tenant/service + CLI):** `write_graph_tenant()` in `writer.py` writes
entities, relationships, and `:Chunk-[:MENTIONS]->:__Entity__` edges in a single call,
all keyed by `(tenant, id)`. There is no separate join step — chunks and entities land
in the same tenant-scoped subgraph atomically:

```cypher
UNWIND $mentions AS m
MATCH (c:Chunk {tenant: $tenant, chunk_id: m.chunk_id})
MATCH (e:__Entity__ {tenant: $tenant, id: m.entity_id})
MERGE (c)-[:MENTIONS]->(e)
```

**Eval/debug path only (langchain `add_graph_documents`):** `write_graph_documents()`
(via `langchain-neo4j`) creates entities attached to its **own** source `:Document` nodes
keyed by `id` (our `chunk_id`). Separately, `write_chunks` creates our `:Chunk` nodes.
Without an explicit join, the embedded chunks and the extracted entities live in
**disjoint subgraphs** — vector search finds chunks, but graph expansion finds nothing,
silently degrading answers to plain RAG.

`link_chunks_to_entities()` repairs this for the eval/debug path by matching on the
shared key and adding the edge:

```cypher
MATCH (src:Document)-[:MENTIONS]->(e)
WHERE src.id IS NOT NULL
MATCH (c:Chunk {chunk_id: src.id})
MERGE (c)-[:MENTIONS]->(e)
```

This join is only needed on the eval/debug (frozen replay) path — the production
`write_graph_tenant` path creates the `:MENTIONS` edges directly and does not require it.

---

## 6. Graph Schema

```
(:Document {source, tenant})
   └─[:HAS_CHUNK]──▶ (:Chunk {chunk_id, text, tenant})
                        └─[:MENTIONS]──▶ (:__Entity__ {id, tenant, …})
                                            ├─[:FOUNDED]────▶ (:__Entity__)
                                            ├─[:ACQUIRED]───▶ (:__Entity__)
                                            ├─[:LOCATED_IN]─▶ (:__Entity__)
                                            └─[:<REL_TYPE>]─▶ (:__Entity__)
```

| Node | Labels | Key properties | Role |
|------|--------|----------------|------|
| Document | `:Document` | `source`, `tenant` | Provenance root (file path), tenant-scoped |
| Chunk | `:Chunk` | `chunk_id`, `text`, `tenant` | Graph anchor; **no embedding stored** — vectors live in Weaviate |
| Entity | `:__Entity__` + domain label | `id`, `tenant`, LLM-derived props | Graph node; composite `(tenant, id)` key enforces isolation |

**No vector index in Neo4j.** Embeddings are stored in Weaviate (collection `Chunk`, property
`tenant` used as a filter). The CLI/demo/eval path calls `vectorstore.search()` against
Weaviate; the service path (`api.py` / `mcp_server.py`) never touches the vector layer —
it receives `chunk_ids` from the platform and expands the graph from them.

Composite uniqueness constraints (enforced in Neo4j):

```cypher
CREATE CONSTRAINT chunk_tenant_key IF NOT EXISTS
FOR (c:Chunk) REQUIRE (c.tenant, c.chunk_id) IS UNIQUE;

CREATE CONSTRAINT entity_tenant_key IF NOT EXISTS
FOR (e:__Entity__) REQUIRE (e.tenant, e.id) IS UNIQUE;
```

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

`query(cfg, question, k=4, hops=1)` (CLI/eval path):

```
"Who founded Acme Corp?"          graphrag query "<question>" [--k 4] [--hops 1]
  │
  ▼ embed question                 providers.get_embeddings()
  ▼ vectorstore.search(k)          Weaviate near-vector query, tenant-filtered
  │      → top-k chunks {chunk_id, text, source, score}
  ▼ expander.expand(chunk_ids, hops)
  │      (:Chunk)-[:MENTIONS]->(e)-[r*1..hops]-(neighbor:__Entity__)  → facts {subject, predicate, object}
  │      (tenant-scoped path guard; skips hub entities over max_degree; deterministic order; Cypher LIMIT candidate_limit)
  ▼ rerank.rerank_facts(question, facts, top_n)   optional BGE cross-encoder; fails closed to expander order → top_n
  ▼ qa.build_context(chunks, facts)
  │      ## Passages  [source] text …
  │      ## Known facts  - subject PREDICATE object …
  ▼ qa.answer(llm, question, chunks, facts)   PROMPT | llm
  │
  ▼ grounded answer with source citations
```

The service-path retrieve (`service.retrieve`) starts at step 3 — the platform supplies
`chunk_ids` directly and the service never calls the vector layer. It applies the same
`expand → rerank → top_n` steps and returns the facts (no `build_context`/`answer`).

- **Hybrid retrieval** — dense (chunk vectors) + structured (entity neighborhood) context.
- **Configurable hops** — `--hops 0` is chunks-only; `1` adds direct neighbors; `2` adds
  friends-of-friends. Variable-length Cypher bounded by `candidate_limit` (default 500)
  prevents runaway expansion, and `max_degree` (default 50) skips traversal through hub
  entities. Every path node must be a tenant `:__Entity__`, so traversal never crosses
  tenants or drifts onto id-less nodes.
- **Reranking (optional, fails closed)** — when a `question` is supplied and the `rerank`
  extra + model are present, a local BGE cross-encoder reorders facts and truncates to
  `top_n`; if the package/model is absent or scoring errors, it falls back to the
  expander's deterministic order rather than failing the request.
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
| Rerank extra/model absent | Fail closed to deterministic expander order | `retrieval/rerank.py`, `service.py` |
| Runaway graph expansion | `candidate_limit` budget + `max_degree` hub skip | `retrieval/expander.py` |
| Missing facts at query | Fall back to chunk-only context | `retrieval/pipeline.py` |

---

## 10. External Services

| Service | Purpose | Endpoint / Access |
|---------|---------|-------------------|
| Neo4j | Graph store (entities, relationships, chunk anchors — **no embeddings**) | `bolt://localhost:7687`, browser at `:7474` |
| Weaviate | Vector index (CLI/demo/eval path only) | HTTP `localhost:8080`, gRPC `localhost:50051` |
| OpenAI | LLM + embeddings | API key via `.env` (`OPENAI_API_KEY`); `OPENAI_BASE_URL` for gateway |

Both Neo4j and Weaviate start via `docker compose up -d` (or `podman compose up -d`). The
`./scripts/neo4j-up.sh` fallback starts Neo4j only.

**Gateway embeddings.** When `OPENAI_BASE_URL` points at the LLM gateway,
`providers.get_embeddings` builds `OpenAIEmbeddings` with `check_embedding_ctx_length=False`
so each `input` item is sent as a raw string. LangChain's default tiktoken-encodes text into
integer token-ID arrays, which `api.openai.com` accepts but the gateway rejects with
`400 invalid_input: Each 'input' array item must be a string`. The default (with client-side
context-length splitting) is preserved when talking to `api.openai.com` directly.

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

## 12. Service / Vector Boundary Invariant

The service path (`service.py`, `api.py`, `mcp_server.py`) is **graph-only**. It must never
import `weaviate` or `graphrag.vectorstore`. This is enforced by a static source check in
`tests/test_boundary.py`:

- **Why**: in production the platform owns vectors (Weaviate or equivalent); the graph service
  receives `chunk_ids` and expands from them. Importing the vector layer in the service would
  couple it to a Weaviate deployment that doesn't exist there.
- **CLI/demo/eval**: `graphrag/vectorstore.py` is the vector capability for local use. The CLI
  `ingest` builds both the Neo4j graph and the Weaviate index; `graphrag query` runs Weaviate
  vector search → graph expansion. The demo's Live mode does the same via `demos/server.py`:
  its image bakes in the `rerank` extra + BGE cross-encoder (CPU-only torch, model pre-pulled),
  so Live reranks exactly like the production service, highlights the answer subgraph, and labels
  facts recovered by expansion beyond the vector hits as **graph-only**.

---

## 13. Extension Points

All fit within current interfaces — no breaking changes required:

1. **More providers** — add branches in `providers.py` (Anthropic, Azure, Ollama/local).
2. **Entity deduplication** — merge `Acme Corp` / `Acme` into one node post-ingest.
3. **Typed relationship constraints** — `(Person, FOUNDED, Company)` triples vs. flat strings.
4. **Async / parallel extraction** — fan out per-chunk LLM calls.
5. **Community detection** — cluster entities and summarize per community (GraphRAG-style).
