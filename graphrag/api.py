"""FastAPI wrapper — the sole external surface of the graph service.

Endpoints: GET /health, POST /retrieve, /ingest, /delete. The three data
endpoints fail closed behind mTLS: nginx terminates the client cert and injects
`X-SSL-Client-Verify` + `X-SSL-Client-DN`; the app rejects anything that isn't a
verified, allow-listed caller CN. /health is open (liveness probe).

TRUST MODEL — the app trusts the `X-SSL-Client-*` headers and the `X-Tenant`
header ONLY because it binds to loopback behind the mTLS-terminating nginx. A
client that could reach the app directly could forge all of them, so it MUST
NEVER be exposed directly (bind 127.0.0.1, nginx upstream only).

Tenant is NOT derived from the cert: the client cert is a *service* identity
(e.g. web-tier / rag-worker) that serves all tenants. Tenant comes from
`X-Tenant`, which is trustworthy here because only an authenticated, allow-listed
service can reach the endpoint to set it. It is threaded into every query.

A single pooled, long-lived Neo4j driver is shared across requests (not a
per-request get_graph). Handlers are sync `def`, so Starlette runs them in its
threadpool and concurrent tenants don't serialize while waiting on Neo4j.
"""

import os
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from graphrag.config import Config, load_config
from graphrag.ingestion.pipeline import ingest_chunks
from graphrag.ingestion.writer import create_constraints, delete_source, get_graph
from graphrag.retrieval.service import retrieve

# Matches CN in both RFC2253 ("CN=foo,OU=bar") and legacy ("/CN=foo/OU=bar") DNs.
_CN_RE = re.compile(r"CN=([^,/]+)")


def _parse_cn(dn: str | None) -> str | None:
    m = _CN_RE.search(dn or "")
    return m.group(1).strip() if m else None


def _allowed_clients_from_env() -> set[str]:
    raw = os.environ.get("GRAPHRAG_ALLOWED_CLIENTS", "")
    return {c.strip() for c in raw.split(",") if c.strip()}


class ChunkIn(BaseModel):
    chunk_id: str
    text: str
    source: str = "unknown"


class RetrieveReq(BaseModel):
    chunk_ids: list[str]
    # Bounded: hops feeds the variable-length pattern [r*1..hops], so 0/negative
    # would 500 and large values are expensive (degree/budget clamp is config-side).
    hops: int = Field(1, ge=1, le=5)
    # Optional: the question the platform vector-searched with. Present -> facts are
    # cross-encoder reranked; absent -> deterministic expander order.
    question: str | None = None
    top_n: int | None = Field(default=None, ge=1, le=200)


class IngestReq(BaseModel):
    chunks: list[ChunkIn]


class DeleteReq(BaseModel):
    source: str


def require_tenant(x_tenant: str | None = Header(default=None)) -> str:
    if not x_tenant:
        raise HTTPException(status_code=400, detail="X-Tenant header required")
    return x_tenant


def create_app(cfg: Config | None = None, allowed_clients: set[str] | None = None) -> FastAPI:
    cfg = cfg or load_config("config.yaml")
    # Fail closed: an unset/empty allow-list rejects every caller. A misconfig
    # must shut the door, not open it.
    allowed = _allowed_clients_from_env() if allowed_clients is None else set(allowed_clients)

    graph = get_graph(cfg)  # pooled driver, reused across requests
    create_constraints(graph)

    def require_client(
        x_ssl_client_verify: str | None = Header(default=None),
        x_ssl_client_dn: str | None = Header(default=None),
    ) -> str:
        # nginx sets Verify=SUCCESS only when the client cert chains to the trust
        # bundle. Anything else (None when bypassing the proxy, FAILED, NONE) -> 403.
        if x_ssl_client_verify != "SUCCESS":
            raise HTTPException(status_code=403, detail="client certificate not verified")
        cn = _parse_cn(x_ssl_client_dn)
        if not cn or cn not in allowed:
            raise HTTPException(status_code=403, detail="client not allowed")
        return cn

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        graph.close()

    app = FastAPI(title="graphrag", lifespan=lifespan)

    @app.get("/health")
    def health():
        graph.query("RETURN 1 AS ok")
        return {"status": "ok"}

    @app.post("/retrieve")
    def retrieve_ep(req: RetrieveReq, client: str = Depends(require_client),
                    tenant: str = Depends(require_tenant)):
        return {"facts": retrieve(graph, tenant, req.chunk_ids, req.hops,
                                  max_degree=cfg.expander.max_degree,
                                  candidate_limit=cfg.expander.candidate_limit,
                                  question=req.question,
                                  top_n=req.top_n or cfg.expander.top_n,
                                  rerank_model=cfg.expander.rerank_model)}

    @app.post("/ingest")
    def ingest_ep(req: IngestReq, client: str = Depends(require_client),
                  tenant: str = Depends(require_tenant)):
        # Reuse the pooled driver, not a fresh per-request one.
        return ingest_chunks(cfg, tenant, [c.model_dump() for c in req.chunks], graph=graph)

    @app.post("/delete")
    def delete_ep(req: DeleteReq, client: str = Depends(require_client),
                  tenant: str = Depends(require_tenant)):
        return delete_source(graph, tenant, req.source)

    return app


# uvicorn graphrag.api:create_app --factory  --  bind 127.0.0.1 only, nginx (mTLS) upstream.
