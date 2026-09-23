"""FastAPI service: query the pipeline and explore the graph over HTTP.

A thin HTTP layer over the same route_query → synthesize_answer path
scripts/ask.py runs — no retrieval logic lives here. Handlers are plain
`def`, not `async def`, so FastAPI runs the blocking Groq/HF calls in its
threadpool instead of stalling the event loop.

Endpoints:
    GET  /                 minimal chat + graph-visualization page
    GET  /health           graph/corpus sizes
    POST /query            routed, cited answer + the subgraph it traversed
    GET  /graph/explore    ego-subgraph around a named entity
    POST /ingest           start a background rebuild of every artifact (202 + job id)
    GET  /ingest           recent ingest jobs, newest first
    GET  /ingest/{job_id}  one job's status, per-step progress, and log tail

The /ingest endpoints require an `X-API-Key` header matching
INGEST_API_KEY; with no key configured they're disabled (503) rather than
open, since a job rebuilds and replaces every artifact.
"""

import os
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import groq
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from huggingface_hub.errors import HfHubHTTPError
from pydantic import BaseModel, Field

from ..graph import ego_subgraph
from ..router import route_query
from ..synthesis import synthesize_answer
from .ingest import IngestInProgressError, IngestManager, IngestRequest
from .resources import Resources, load_resources
from .views import result_subgraph

STATIC_DIR = Path(__file__).parent / "static"


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


def create_app(
    resources: Resources | None = None,
    loader: Callable[[], Resources] = load_resources,
    ingest_manager: IngestManager | None = None,
    ingest_api_key: str | None = None,
) -> FastAPI:
    """Build the app. Pass `resources` directly (tests) or let startup call `loader`.

    A successful ingest job reloads through the same `loader` and swaps
    app.state.resources in one assignment, so in-flight queries finish on
    the old artifacts and later ones see the new.
    """
    ingest_manager = ingest_manager if ingest_manager is not None else IngestManager(loader)
    ingest_api_key = ingest_api_key if ingest_api_key is not None else os.environ.get("INGEST_API_KEY", "")

    def require_ingest_key(x_api_key: str | None = Header(default=None)) -> None:
        if not ingest_api_key:
            raise HTTPException(status_code=503, detail="ingest is disabled: set INGEST_API_KEY to enable it")
        if x_api_key is None or not secrets.compare_digest(x_api_key, ingest_api_key):
            raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.resources = resources if resources is not None else loader()
        yield

    app = FastAPI(title="EntityGraph-RAG", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health(request: Request) -> dict:
        res: Resources = request.app.state.resources
        return {
            "status": "ok",
            "nodes": res.store.node_count(),
            "edges": res.store.edge_count(),
            "chunks": len(res.chunks_by_id),
        }

    @app.post("/query")
    def query(body: QueryRequest, request: Request) -> dict:
        res: Resources = request.app.state.resources
        try:
            result = route_query(
                body.query,
                client=res.client,
                embedding_client=res.embedding_client,
                schema=res.schema,
                store=res.store,
                index=res.index,
                chunks_by_id=res.chunks_by_id,
                entity_lookup=res.entity_lookup,
                top_k=body.top_k,
            )
            synthesis = synthesize_answer(result, chunks_by_id=res.chunks_by_id, client=res.client)
        except (groq.APIError, HfHubHTTPError) as e:
            raise HTTPException(status_code=502, detail=f"upstream provider error: {e}")

        return {
            **synthesis,
            "classification_reasoning": result["classification_reasoning"],
            "warning": result.get("warning"),
            "subgraph": result_subgraph(result, res.store),
        }

    @app.get("/graph/explore")
    def graph_explore(
        request: Request,
        entity: str = Query(min_length=1, description="entity name or alias, fuzzy-matched"),
        depth: int = Query(default=1, ge=1, le=3),
        max_nodes: int = Query(default=200, ge=1, le=1000),
    ) -> dict:
        res: Resources = request.app.state.resources
        entity_id = res.entity_lookup.resolve(entity)
        if entity_id is None:
            raise HTTPException(status_code=404, detail=f"no known entity matches {entity!r}")
        return {"entity_id": entity_id, **ego_subgraph(res.store, entity_id, depth=depth, max_nodes=max_nodes)}

    @app.post("/ingest", status_code=202, dependencies=[Depends(require_ingest_key)])
    def ingest(body: IngestRequest) -> dict:
        def swap_resources(new: Resources) -> None:
            app.state.resources = new

        try:
            job = ingest_manager.start(body, on_reloaded=swap_resources)
        except IngestInProgressError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return job.to_dict()

    @app.get("/ingest", dependencies=[Depends(require_ingest_key)])
    def ingest_jobs() -> list[dict]:
        return [job.to_dict() for job in ingest_manager.all_jobs()]

    @app.get("/ingest/{job_id}", dependencies=[Depends(require_ingest_key)])
    def ingest_status(job_id: str) -> dict:
        job = ingest_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no ingest job {job_id!r}")
        return job.to_dict()

    return app
