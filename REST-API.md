# REST API

The HTTP surface of the graph-retrieval service (`graphrag/api.py`). It is the
primary, secured interface used by the platform. The service is graph-only:
Neo4j holds entities, relationships, and lightweight `:Chunk` anchors keyed by
the platform's `chunk_id`. No vectors are stored here (Weaviate owns those).

## Running

```bash
uvicorn graphrag.api:create_app --factory
```

Bind to loopback only and put the mTLS-terminating nginx in front (see
**Authentication**). The app must never be exposed directly: it trusts headers
that nginx sets, and a direct caller could forge them.

`create_app(cfg=None, allowed_clients=None)` builds the app with one pooled,
long-lived Neo4j driver. Handlers are synchronous, so Starlette runs them in a
threadpool and concurrent tenants do not serialize.

## Authentication and tenancy

mTLS is terminated by nginx, which verifies the client certificate against the
Knockout CA trust bundle and injects two headers on every proxied request:

| Header | Meaning |
| --- | --- |
| `X-SSL-Client-Verify` | `SUCCESS` when the client cert chained to the trust bundle |
| `X-SSL-Client-DN` | the client certificate distinguished name (CN is parsed from it) |

The three data endpoints (`/retrieve`, `/ingest`, `/delete`) fail closed:

1. `403` unless `X-SSL-Client-Verify` is `SUCCESS`.
2. `403` unless the CN parsed from `X-SSL-Client-DN` is in `GRAPHRAG_ALLOWED_CLIENTS`
   (comma-separated). An unset or empty allow-list rejects every caller.
3. `400` if `X-Tenant` is missing.

`/health` is open (no headers required).

The client certificate is a service identity (for example `rag-worker`), not a
tenant. Those services serve many tenants, so the tenant is taken from the
`X-Tenant` header. That header is trustworthy only because the app sits on
loopback behind the mTLS proxy.

nginx requirement: every location that proxies to the app must set both
`X-SSL-Client-Verify` and `X-SSL-Client-DN` with `proxy_set_header` (overwriting
any client-supplied copy). If a proxied path forwards a client-supplied value,
the guard can be bypassed.

## Endpoints

### `GET /health`

Liveness. Runs a trivial Neo4j query. No authentication.

```json
200 OK
{"status": "ok"}
```

### `POST /retrieve`

Expand the tenant's graph from the given `chunk_ids` and return facts.

Request body:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `chunk_ids` | `string[]` | required | platform chunk ids to anchor on |
| `hops` | `int` | `1` | traversal depth, bounded `1..5` |
| `question` | `string \| null` | `null` | if set, facts are reranked by a local cross-encoder |
| `top_n` | `int \| null` | `null` | facts kept after rank/truncate; falls back to the configured default |

Response:

```json
200 OK
{"facts": [{"subject": "Acme Corp", "predicate": "ACQUIRED", "object": "Beta Labs"}]}
```

Facts are entity-to-entity triples only (no `:MENTIONS`/`:HAS_CHUNK` edges, no
null endpoints). Without `question`, facts come back in a deterministic order
(hop distance, then subject/predicate/object) truncated to `top_n`. With
`question`, they are reranked against it and truncated to `top_n`.

Errors: `403` (cert not verified or CN not allowed), `400` (missing `X-Tenant`),
`422` (validation, for example `hops` outside `1..5`).

Example (the external client presents a cert to nginx; nginx injects the
`X-SSL-*` headers):

```bash
curl --cert client.crt --key client.key \
  -H "X-Tenant: acme" -H "Content-Type: application/json" \
  -d '{"chunk_ids": ["c1", "c2"], "hops": 2, "question": "Who is the CTO of Acme?"}' \
  https://graphrag.internal/retrieve
```

### `POST /ingest`

Ingest pre-chunked content for a tenant. The platform owns chunking and supplies
`chunk_id` (its key into Weaviate). This path extracts a graph with the LLM, so
the gateway (`OPENAI_BASE_URL` / `OPENAI_API_KEY`) must be configured.
Re-ingesting a source replaces it (reconcile by source), so edited content whose
`chunk_id` changes leaves no stale chunks or entities.

Request body:

```json
{"chunks": [{"chunk_id": "c1", "text": "Acme Corp acquired Beta Labs.", "source": "doc.txt"}]}
```

Response:

```json
200 OK
{"chunks": 1, "graph_documents": 1, "extraction_failures": 0}
```

### `POST /delete`

Remove a source's `:Chunk` nodes, their `:MENTIONS` edges, and any entities
thereby orphaned, scoped to the tenant. Idempotent.

```json
// request
{"source": "doc.txt"}

// response
{"source": "doc.txt", "tenant": "acme", "candidate_entities": 3}
```

## Configuration

Environment:

| Variable | Purpose |
| --- | --- |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | Neo4j connection (loopback) |
| `GRAPHRAG_ALLOWED_CLIENTS` | comma-separated client CNs allowed to call the data endpoints; empty rejects all |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY` | LLM gateway, used by `/ingest` extraction only |

`config.yaml` `expander:` block:

| Key | Default | Purpose |
| --- | --- | --- |
| `max_degree` | `50` | do not expand through entities above this entity-to-entity degree |
| `candidate_limit` | `200` | deterministic fact budget before rerank |
| `top_n` | `10` | facts kept after rerank/truncate |
| `rerank_model` | `BAAI/bge-reranker-base` | local cross-encoder for `/retrieve` with `question` |

Reranking needs the optional `rerank` extra (`pip install -e ".[rerank]"`) and
the model present locally. If the dependency or model is missing, `/retrieve`
falls back to deterministic ordering.

## Notes

- Neo4j binds to loopback only; it is never on the mesh.
- The vector path in the repo (`retrieval/pipeline.py`, `vector.py`, the CLI
  `query` command) is an eval/debug surface, not part of this service.
