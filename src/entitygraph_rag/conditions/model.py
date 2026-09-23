"""Generate the LLM output model for advisory-text extraction from the schema.

Only edge types marked `extraction: llm` are used (in schema v2 that is
EXPLOITABLE_WHEN alone). The subject of every such edge is the advisory the
chunk came from, so the LLM never names it. It returns the object node's
properties, with closed vocabularies (`property_values`) as Literal types,
plus a verbatim `evidence` quote and a confidence.
"""

from typing import Literal

from pydantic import BaseModel, Field, create_model

from ..extraction.schema import Schema

DOCUMENT_TYPE = "Vulnerability"  # the node type an advisory chunk is about


def object_node_types(schema: Schema) -> list[str]:
    llm_edges = schema.llm_edge_types()
    if not llm_edges:
        raise ValueError(f"schema v{schema.version} declares no llm edge types")
    for name, edge in llm_edges.items():
        if DOCUMENT_TYPE not in edge.subject_types:
            raise ValueError(f"{name}: subject must be {DOCUMENT_TYPE}, the node an advisory chunk describes")
    return sorted({t for edge in llm_edges.values() for t in edge.object_types})


def build_extraction_model(schema: Schema) -> type[BaseModel]:
    fields: dict = {"relation": (Literal[tuple(schema.llm_edge_types())], ...)}
    for type_name in object_node_types(schema):
        node = schema.node_types[type_name]
        for prop in node.properties:
            values = node.property_values.get(prop)
            fields[prop] = (Literal[tuple(values)], ...) if values else (str, ...)
    fields["evidence"] = (str, ...)
    fields["confidence"] = (float, Field(ge=0.0, le=1.0))
    return create_model("Extraction", **fields)
