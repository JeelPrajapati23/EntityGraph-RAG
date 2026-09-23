"""FastAPI service: ask DepGraph questions and explore the graph over HTTP.

A thin HTTP layer over the same route_query -> synthesize_answer path
scripts/ask_depgraph.py runs; no retrieval logic lives here. Handlers are
plain `def`, not `async def`, so FastAPI runs the blocking Groq/HF calls in
its threadpool instead of stalling the event loop.

Endpoints:
    GET  /                 chat + graph-visualization page
    GET  /health           graph / advisory-index sizes
    POST /query            routed, cited answer + the subgraph it traversed
    GET  /graph/explore    ego-subgraph around a package, version or advisory

Rebuilding the data is done with the scripts/ build steps, not over HTTP.
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import groq
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from huggingface_hub.errors import HfHubHTTPError
from pydantic import BaseModel, Field

from ..depgraph import route_query
from ..depgraph.synthesis import synthesize_answer
from ..graph import ego_subgraph
from .resources import Resources, load_resources
from .views import result_subgraph

STATIC_DIR = Path(__file__).parent / "static"


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


def create_app(resources: Resources | None = None, loader: Callable[[], Resources] = load_resources) -> FastAPI:
    """Build the app. Pass `resources` directly (tests) or let startup call `loader`."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.resources = resources if resources is not None else loader()
        yield

    app = FastAPI(title="reachfix", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health(request: Request) -> dict:
        ctx = request.app.state.resources.ctx
        return {
            "status": "ok",
            "nodes": ctx.store.node_count(),
            "edges": ctx.store.edge_count(),
            "advisory_chunks": len(ctx.chunks_by_id),
            "remediation": ctx.releases is not None,
        }

    @app.post("/query")
    def query(body: QueryRequest, request: Request) -> dict:
        res: Resources = request.app.state.resources
        try:
            result = route_query(body.query, client=res.client, ctx=res.ctx, schema=res.schema, top_k=body.top_k)
            answer = synthesize_answer(result, client=res.client)
        except (groq.APIError, HfHubHTTPError) as e:
            raise HTTPException(status_code=502, detail=f"upstream provider error: {e}")

        return {
            **answer,
            "pattern": result["pattern"],
            "executed_pattern": result["executed_pattern"],
            "classification_reasoning": result["classification_reasoning"],
            "subgraph": result_subgraph(result, res.ctx.store),
        }

    @app.get("/graph/explore")
    def graph_explore(
        request: Request,
        entity: str = Query(min_length=1, description="package, name@version, or GHSA/CVE id"),
        depth: int = Query(default=1, ge=1, le=3),
        max_nodes: int = Query(default=200, ge=1, le=1000),
    ) -> dict:
        store = request.app.state.resources.ctx.store
        matches = request.app.state.resources.ctx.lookup.resolve(entity)
        if not matches:
            raise HTTPException(status_code=404, detail=f"no package, version or advisory matches {entity!r}")
        # A CVE can map to several advisories; the first is drawn and all are listed.
        return {"entity_id": matches[0], "matches": matches,
                **ego_subgraph(store, matches[0], depth=depth, max_nodes=max_nodes)}

    return app
