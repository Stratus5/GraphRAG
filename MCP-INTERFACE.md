# MCP Interface

An optional [Model Context Protocol](https://modelcontextprotocol.io) server
(`graphrag/mcp_server.py`) that exposes the graph service as MCP tools, so an MCP
client (an IDE, a desktop assistant, an agent) can search and maintain a
tenant's graph. It is a standalone, general-purpose surface, separate from the
platform deployment.

## Scope and security

This is NOT the secured platform path. The platform uses the mTLS REST wrapper
(see `REST-API.md`). The MCP server has no mTLS and no client-cert allow-list, so:

- `tenant` is a required argument on every tool. There is no ambient tenant.
- the transport must be secured by whatever runs it (stdio for a local client,
  or an authenticated HTTP transport). Do not expose it unauthenticated.

It shares the same tenant-scoped service functions and one pooled, lazily-opened
Neo4j driver, so tenant isolation behaves exactly as it does over REST.

## Running

```bash
pip install -e ".[mcp]"
python -m graphrag.mcp_server          # stdio transport
```

Example client registration (stdio):

```json
{
  "mcpServers": {
    "graphrag": {
      "command": "python",
      "args": ["-m", "graphrag.mcp_server"]
    }
  }
}
```

It reads the same `config.yaml` and environment as the rest of the service
(`NEO4J_*`, and `OPENAI_*` for `ingest` extraction). For an HTTP transport,
configure it per the MCP SDK and front it with auth.

## Tools

### `retrieve`

Expand the tenant's graph from `chunk_ids` and return facts.

| Argument | Type | Default | Notes |
| --- | --- | --- | --- |
| `tenant` | `string` | required | tenant key; queries are scoped to it |
| `chunk_ids` | `string[]` | required | platform chunk ids to anchor on |
| `hops` | `int` | `1` | traversal depth (`1..5` recommended) |
| `question` | `string \| null` | `null` | if set, facts are reranked by a local cross-encoder |
| `top_n` | `int \| null` | `null` | facts kept after rank/truncate; falls back to the configured default |

Returns a list of `{subject, predicate, object}` triples (entity-to-entity only,
no `:MENTIONS`/`:HAS_CHUNK`, no null endpoints).

### `ingest`

Ingest pre-chunked content for a tenant. Extracts a graph with the LLM, so the
gateway (`OPENAI_BASE_URL` / `OPENAI_API_KEY`) must be configured. Re-ingesting a
source replaces it (reconcile by source).

| Argument | Type | Notes |
| --- | --- | --- |
| `tenant` | `string` | tenant key |
| `chunks` | `object[]` | each `{chunk_id, text, source}` (`source` optional) |

Returns `{chunks, graph_documents, extraction_failures}`.

### `delete`

Remove a source's chunks, mentions, and orphaned entities for a tenant.

| Argument | Type |
| --- | --- |
| `tenant` | `string` |
| `source` | `string` |

Returns `{source, tenant, candidate_entities}`.

### `health`

Confirm Neo4j is reachable. Returns `{status: "ok"}`.

## Relationship to the REST API

`api.py` (REST) and `mcp_server.py` (MCP) are **siblings** — independent wrappers over the
same service functions (`retrieve`, `ingest_chunks`, `delete_source`) and the same pooled
Neo4j driver, with identical tenant scoping. Neither is derived from the other.

MCP tools are **not** auto-derived from the FastAPI app. The reason is that the trust models
are fundamentally different:

- **REST** is fronted by an external nginx that terminates mTLS and injects the verified
  client CN as an HTTP header. The FastAPI app reads that header but never handles TLS itself.
  This header-trust pattern does not transfer to MCP transports (stdio, SSE, etc.), which have
  no equivalent injection point.
- **MCP** takes `tenant` as an explicit tool argument and relies entirely on the transport
  layer for authentication (the caller controls the stdio process or the HTTP transport). An
  auto-generated MCP surface from FastAPI route introspection would silently drop the
  mTLS/CN semantics and produce a security boundary mismatch.

The difference is the trust model: REST enforces mTLS + a client-CN allow-list (deploy-only,
external nginx); MCP relies on its transport for auth and takes the tenant as an explicit
argument. Use REST for the platform; use MCP for local tooling and general-purpose clients.
