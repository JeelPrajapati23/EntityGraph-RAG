"""LLM-based query classification: which retrieval path does this query need?

Structured output, same pattern as extraction/schema.py — the relation
Literal type is generated from schema/v1.yaml so the router can never
propose a relation type outside the fixed vocabulary.
"""

from typing import Literal

from pydantic import BaseModel, create_model

from ..extraction.schema import Schema

ROUTES = ("semantic", "relational", "graph_guided_hybrid")
GRAPH_PATTERNS = ("neighbors", "two_hop", "common_neighbors")


def build_router_decision_model(schema: Schema) -> type[BaseModel]:
    relation_names = tuple(schema.edge_types)

    return create_model(
        "RouterDecision",
        route=(Literal[ROUTES], ...),
        entities=(list[str], ...),
        relation=(Literal[relation_names] | None, None),
        graph_pattern=(Literal[GRAPH_PATTERNS] | None, None),
        reasoning=(str, ...),
    )


def build_classification_prompt(schema: Schema) -> str:
    relation_lines = "\n".join(f"- {name}: {edge.description}" for name, edge in schema.edge_types.items())

    return f"""You are a query router for a hybrid retrieval system over financial \
documents (SEC filings and earnings-call transcripts). There are two \
retrieval mechanisms available: a vector search index over document \
chunks, and a knowledge graph of typed relations between companies, \
people, products, locations, and risks.

Classify the query into exactly one route:
- semantic: a factual/descriptive question best answered directly from \
document text (e.g. "what risks does NVIDIA disclose about supply chain \
concentration?"). No specific graph traversal needed.
- relational: a question that is fundamentally about one specific typed \
relationship in the graph (e.g. "who supplies NVIDIA?", "who are NVIDIA's \
competitors?", "who audits Apple?"). Extract the named entities and, if \
identifiable, the relation type and graph_pattern.
- graph_guided_hybrid: a question that needs graph context to scope a \
broader answer from document text (e.g. "what has NVIDIA said about its \
relationship with TSMC?") — mentions specific entities but isn't a single \
crisp relation lookup.

Relation vocabulary (only use these values for "relation" — never invent one):
{relation_lines}

graph_pattern (only set when route="relational"):
- neighbors: a single entity's relations of one type (e.g. "who does \
NVIDIA supply?")
- two_hop: a two-step chain (e.g. "who supplies NVIDIA's suppliers?")
- common_neighbors: entities related the same way to BOTH of two named \
entities (e.g. "who supplies both NVIDIA and Apple?")

entities: every entity name mentioned in the query, exactly as written \
(empty list if none).
reasoning: one sentence on why you chose this route.

Return only a JSON object with exactly these keys: "route" (one of \
{", ".join(ROUTES)}), "entities" (list of strings), "relation" (one of the \
relation names above, or null), "graph_pattern" (one of \
{", ".join(GRAPH_PATTERNS)}, or null), "reasoning" (string)."""
