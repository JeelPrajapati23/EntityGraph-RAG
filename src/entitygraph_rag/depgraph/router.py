"""DepGraph router: classify a query, then dispatch it to the graph, the advisory index, or both.

Plain Python, like the finance router: one LLM call classifies, and a plain
if/elif dispatches. Every result records the route, the classifier's
reasoning and how each named entity resolved, so a wrong answer can be
traced to classification, resolution or retrieval.
"""

import json
from pathlib import Path

from groq import Groq
from huggingface_hub import InferenceClient
from pydantic import BaseModel, ValidationError

from ..extraction.schema import Schema
from ..graph import NetworkXGraphStore
from ..llm_client import DEFAULT_MODEL, generate_json
from ..npm.advisory_index import DEFAULT_VARIANT, index_path
from ..npm.lookup import NodeLookup
from ..retrieval import VectorIndex
from .classify import build_classification_prompt, build_decision_model
from .dispatch import DepGraphContext, resolve, run_graph_guided_hybrid, run_relational, semantic_chunks

CLASSIFY_ATTEMPTS = 2
FALLBACK_REASONING = "classifier returned invalid output twice; fell back to semantic search"


def classify_query(query: str, *, client: Groq, schema: Schema, model_name: str = DEFAULT_MODEL) -> BaseModel:
    """Classify `query`, retrying once on invalid output, then falling back to semantic.

    Groq's JSON mode doesn't enforce enum values, so a misspelled route,
    pattern or relation fails validation. Semantic search needs no entities,
    so it can always run.
    """
    decision_model = build_decision_model(schema)
    system_prompt = build_classification_prompt(schema)
    for _ in range(CLASSIFY_ATTEMPTS):
        raw = generate_json(client, system_prompt=system_prompt, user_prompt=query, model_name=model_name)
        try:
            return decision_model.model_validate_json(raw)
        except ValidationError:
            continue
    return decision_model(route="semantic", entities=[], reasoning=FALLBACK_REASONING)


def route_query(query: str, *, client: Groq, ctx: DepGraphContext, schema: Schema,
                model_name: str = DEFAULT_MODEL, top_k: int = 5) -> dict:
    decision = classify_query(query, client=client, schema=schema, model_name=model_name)
    resolved, warnings = resolve(ctx, decision.entities)

    if decision.route == "relational" and resolved:
        result = run_relational(ctx, decision, resolved)
    elif decision.route == "graph_guided_hybrid" and resolved:
        result = run_graph_guided_hybrid(ctx, query, resolved, top_k)
    else:
        if decision.route != "semantic":
            warnings.append(f"{decision.route} route needs a known entity; fell back to semantic search")
        result = {"chunks": semantic_chunks(ctx, query, top_k)}
    executed = "semantic" if decision.route != "semantic" and not resolved else decision.route
    # Dispatch can run a different pattern than classified (see run_relational); keep both.
    executed_pattern = result.pop("pattern", None)

    return {
        "query": query,
        "route": decision.route,
        "executed_route": executed,
        "pattern": decision.pattern,
        "executed_pattern": executed_pattern,
        "relation": decision.relation,
        "classification_reasoning": decision.reasoning,
        "entities": [{"name": name, "node_ids": ids} for name, ids in resolved],
        "warnings": warnings + ([result.pop("warning")] if "warning" in result else []),
        **result,
    }


def load_context(depgraph_dir: Path, embedding_client: InferenceClient, variant: str = DEFAULT_VARIANT) -> DepGraphContext:
    """Everything the router needs, from the Phase 2-6 build outputs."""
    def read_jsonl(name):
        return [json.loads(line) for line in (depgraph_dir / name).read_text(encoding="utf-8").splitlines() if line]

    return DepGraphContext(
        store=NetworkXGraphStore.from_file(depgraph_dir / "graph.pkl"),
        lookup=NodeLookup(read_jsonl("nodes.jsonl")),
        index=VectorIndex.from_file(index_path(depgraph_dir, variant)),
        chunks_by_id={c["chunk_id"]: c for c in read_jsonl("advisory_chunks.jsonl")},
        embedding_client=embedding_client,
        variant=variant,
    )
