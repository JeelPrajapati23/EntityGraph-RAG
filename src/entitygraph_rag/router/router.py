"""Top-level router: classify a query, then dispatch to the matching retrieval path.

Plain Python, not an orchestration framework — a single LLM call classifies
the query, then a plain if/elif dispatches to the existing semantic_search,
GraphStore queries, or the graph-guided-hybrid combination. Every result
carries which route was taken and why, per the project plan's "log which
route was taken per query — useful for debugging and as an evaluation
dimension."
"""

from groq import Groq
from huggingface_hub import InferenceClient
from pydantic import BaseModel, ValidationError

from ..extraction.schema import Schema
from ..graph import GraphStore
from ..llm_client import DEFAULT_MODEL, generate_json
from ..retrieval import VectorIndex, semantic_search
from .classify import build_classification_prompt, build_router_decision_model
from .dispatch import run_graph_guided_hybrid, run_relational
from .entity_lookup import EntityLookup

DEFAULT_CLASSIFIER_MODEL = DEFAULT_MODEL
CLASSIFY_ATTEMPTS = 2
FALLBACK_REASONING = "classifier returned invalid output twice; fell back to semantic search"


def classify_query(
    query: str, *, client: Groq, schema: Schema, model_name: str = DEFAULT_CLASSIFIER_MODEL
) -> BaseModel:
    """Classify `query`, retrying once on output that fails validation.

    Groq's JSON mode doesn't enforce the enum values, so the model
    occasionally misspells a relation (e.g. DISLOSED_RISK). If both attempts
    fail validation, fall back to the semantic route — plain vector search
    needs no entities or relation, so it's always runnable.
    """
    decision_model = build_router_decision_model(schema)
    system_prompt = build_classification_prompt(schema)
    for _ in range(CLASSIFY_ATTEMPTS):
        raw_json = generate_json(client, system_prompt=system_prompt, user_prompt=query, model_name=model_name)
        try:
            return decision_model.model_validate_json(raw_json)
        except ValidationError:
            continue
    return decision_model(route="semantic", entities=[], reasoning=FALLBACK_REASONING)


def route_query(
    query: str,
    *,
    client: Groq,
    embedding_client: InferenceClient,
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
        result = {"route": "semantic", "chunks": semantic_search(query, index=index, chunks_by_id=chunks_by_id, client=embedding_client, top_k=top_k)}
    elif decision.route == "relational":
        result = run_relational(decision, schema=schema, store=store, entity_lookup=entity_lookup)
    else:
        result = run_graph_guided_hybrid(
            query, decision, store=store, entity_lookup=entity_lookup, index=index,
            chunks_by_id=chunks_by_id, embedding_client=embedding_client, top_k=top_k,
        )

    result["query"] = query
    result["classification_reasoning"] = decision.reasoning
    return result
