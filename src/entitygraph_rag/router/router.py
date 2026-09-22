"""Top-level router: classify a query, then dispatch to the matching retrieval path.

Plain Python, not an orchestration framework — a single LLM call classifies
the query, then a plain if/elif dispatches to the existing semantic_search,
GraphStore queries, or the graph-guided-hybrid combination. Every result
carries which route was taken and why, per the project plan's "log which
route was taken per query — useful for debugging and as an evaluation
dimension."
"""

from google import genai
from google.genai import types
from pydantic import BaseModel

from ..extraction.schema import Schema
from ..graph import GraphStore
from ..retrieval import VectorIndex, semantic_search
from .classify import build_classification_prompt, build_router_decision_model
from .dispatch import run_graph_guided_hybrid, run_relational
from .entity_lookup import EntityLookup

DEFAULT_CLASSIFIER_MODEL = "gemini-2.5-flash"


def classify_query(
    query: str, *, client: genai.Client, schema: Schema, model_name: str = DEFAULT_CLASSIFIER_MODEL
) -> BaseModel:
    decision_model = build_router_decision_model(schema)
    response = client.models.generate_content(
        model=model_name,
        contents=query,
        config=types.GenerateContentConfig(
            system_instruction=build_classification_prompt(schema),
            response_mime_type="application/json",
            response_schema=decision_model,
            temperature=0.0,
        ),
    )
    return decision_model.model_validate_json(response.text)


def route_query(
    query: str,
    *,
    client: genai.Client,
    schema: Schema,
    store: GraphStore,
    index: VectorIndex,
    chunks_by_id: dict,
    entity_lookup: EntityLookup,
    classifier_model: str = DEFAULT_CLASSIFIER_MODEL,
    top_k: int = 5,
) -> dict:
    decision = classify_query(query, client=client, schema=schema, model_name=classifier_model)

    if decision.route == "semantic":
        result = {"route": "semantic", "chunks": semantic_search(query, index=index, chunks_by_id=chunks_by_id, client=client, top_k=top_k)}
    elif decision.route == "relational":
        result = run_relational(decision, store=store, entity_lookup=entity_lookup)
    else:
        result = run_graph_guided_hybrid(
            query, decision, store=store, entity_lookup=entity_lookup, index=index,
            chunks_by_id=chunks_by_id, client=client, top_k=top_k,
        )

    result["query"] = query
    result["classification_reasoning"] = decision.reasoning
    return result
