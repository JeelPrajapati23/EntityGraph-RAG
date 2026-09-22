"""Dispatch a classified query to the right retrieval path.

Each path only calls the existing GraphStore/VectorIndex interfaces
(graph/queries.py, retrieval/search.py) — the router adds no new retrieval
mechanics of its own, just the glue between "what did the LLM decide" and
"which existing function answers that." Human-readable graph-path citation
strings and prose are an answer-synthesis concern (see synthesis/), but the
raw ingredients for both — origin entity, relation, and edge provenance —
are included in every result row here so synthesis never has to re-query
the graph.
"""

from huggingface_hub import InferenceClient
from pydantic import BaseModel

from ..graph import GraphStore, common_neighbors, two_hop_neighbors
from ..retrieval import VectorIndex, semantic_search
from .entity_lookup import EntityLookup


def _named(store: GraphStore, entity_id: str) -> dict:
    entity = store.get_entity(entity_id)
    return {"entity_id": entity_id, "canonical_name": entity["canonical_name"] if entity else entity_id}


def _resolve_entities(decision: BaseModel, entity_lookup: EntityLookup) -> list[str]:
    resolved = []
    for name in decision.entities:
        entity_id = entity_lookup.resolve(name)
        if entity_id is not None:
            resolved.append(entity_id)
    return resolved


def run_relational(decision: BaseModel, *, store: GraphStore, entity_lookup: EntityLookup) -> dict:
    entity_ids = _resolve_entities(decision, entity_lookup)
    pattern = decision.graph_pattern or "neighbors"

    if not entity_ids:
        return {"route": "relational", "pattern": pattern, "results": [], "warning": "no known entities matched"}

    if pattern == "common_neighbors" and len(entity_ids) >= 2:
        targets = [_named(store, entity_ids[0]), _named(store, entity_ids[1])]
        shared = common_neighbors(store, entity_ids[0], entity_ids[1], relation=decision.relation, direction="in")
        results = [{**_named(store, e), "relation": decision.relation, "targets": targets} for e in shared]
        return {"route": "relational", "pattern": pattern, "results": results}

    if pattern == "two_hop":
        source = _named(store, entity_ids[0])
        hops = two_hop_neighbors(store, entity_ids[0], relation=decision.relation)
        results = [
            {
                "source": source,
                "via": _named(store, hop["via"]),
                "target": _named(store, hop["target"]),
                "first_relation": decision.relation,
                "relation": hop["relation"],
            }
            for hop in hops
        ]
        return {"route": "relational", "pattern": pattern, "results": results}

    results = []
    for entity_id in entity_ids:
        source = _named(store, entity_id)
        for neighbor in store.neighbors(entity_id, relation=decision.relation, direction="both"):
            results.append(
                {
                    **_named(store, neighbor["entity_id"]),
                    "source": source,
                    "relation": neighbor["relation"],
                    "direction": neighbor["direction"],
                    "confidence": neighbor["confidence"],
                    "provenance": neighbor["provenance"],
                }
            )
    return {"route": "relational", "pattern": pattern, "results": results}


def run_graph_guided_hybrid(
    query: str,
    decision: BaseModel,
    *,
    store: GraphStore,
    entity_lookup: EntityLookup,
    index: VectorIndex,
    chunks_by_id: dict,
    embedding_client: InferenceClient,
    top_k: int = 5,
) -> dict:
    entity_ids = _resolve_entities(decision, entity_lookup)

    expanded_ids = set(entity_ids)
    candidate_chunk_ids: set[str] = set()
    edges = []
    for entity_id in entity_ids:
        source = _named(store, entity_id)
        for neighbor in store.neighbors(entity_id, direction="both"):
            expanded_ids.add(neighbor["entity_id"])
            candidate_chunk_ids.update(mention["source_chunk_id"] for mention in neighbor["provenance"])
            edges.append(
                {
                    **_named(store, neighbor["entity_id"]),
                    "source": source,
                    "relation": neighbor["relation"],
                    "direction": neighbor["direction"],
                    "provenance": neighbor["provenance"],
                }
            )

    # No graph context to scope by (unresolved entities, or entities with no
    # edges yet) — fall back to a plain, unscoped semantic search.
    chunks = semantic_search(
        query,
        index=index,
        chunks_by_id=chunks_by_id,
        client=embedding_client,
        top_k=top_k,
        candidate_chunk_ids=candidate_chunk_ids or None,
    )

    return {
        "route": "graph_guided_hybrid",
        "expanded_entities": [_named(store, entity_id) for entity_id in sorted(expanded_ids)],
        "edges": edges,
        "chunks": chunks,
    }
