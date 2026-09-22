"""Load schema/v1.yaml and generate the Pydantic Triple model from it.

The extraction prompt and the Triple model's Literal types are both derived
from this loaded schema rather than hand-duplicated, so a new schema version
file is the only thing that needs to change to retarget extraction — see
schema/v1.yaml's own header comment.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, create_model

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "schema" / "v1.yaml"


@dataclass
class NodeType:
    name: str
    description: str
    properties: list[str]


@dataclass
class EdgeType:
    name: str
    subject_types: list[str]
    object_types: list[str]
    description: str
    symmetric: bool = False


@dataclass
class Schema:
    version: int
    node_types: dict[str, NodeType]
    edge_types: dict[str, EdgeType]
    edge_properties: list[str]

    def allowed_object_types(self, relation: str) -> set[str]:
        return set(self.edge_types[relation].object_types)

    def allowed_subject_types(self, relation: str) -> set[str]:
        return set(self.edge_types[relation].subject_types)


def _as_list(value: str | list[str]) -> list[str]:
    return value if isinstance(value, list) else [value]


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> Schema:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    node_types = {
        name: NodeType(name=name, description=body["description"].strip(), properties=body.get("properties", []))
        for name, body in raw["node_types"].items()
    }
    edge_types = {
        name: EdgeType(
            name=name,
            subject_types=_as_list(body["subject"]),
            object_types=_as_list(body["object"]),
            description=body["description"].strip(),
            symmetric=body.get("symmetric", False),
        )
        for name, body in raw["edge_types"].items()
    }

    return Schema(
        version=raw["version"],
        node_types=node_types,
        edge_types=edge_types,
        edge_properties=raw["edge_properties"],
    )


def build_triple_model(schema: Schema) -> type[BaseModel]:
    """Build a Pydantic model whose Literal fields are exactly the schema's vocabulary.

    subject_type/object_type are constrained to the full set of node type
    names (the union across all relations) rather than per-relation, since
    structured-output APIs can't express "object_type depends on relation"
    as a field-level constraint. The subject/object-type-per-relation check
    happens as a separate post-hoc validation pass — see validate_triple.

    No extra="forbid" config: Gemini's structured-output schema converter (a
    restricted OpenAPI subset) rejects the resulting `additionalProperties`
    keyword with a 400, and it isn't needed for validation anyway since the
    fields are exhaustively listed and Literal-typed.
    """
    node_type_names = tuple(schema.node_types)
    relation_names = tuple(schema.edge_types)

    return create_model(
        "Triple",
        subject=(str, ...),
        subject_type=(Literal[node_type_names], ...),
        relation=(Literal[relation_names], ...),
        object=(str, ...),
        object_type=(Literal[node_type_names], ...),
        confidence=(float, ...),
    )


def validate_triple(schema: Schema, triple: BaseModel) -> str | None:
    """Return None if triple's subject/object types match its relation's schema, else a reason."""
    edge = schema.edge_types[triple.relation]
    if triple.subject_type not in edge.subject_types:
        return f"{triple.relation} requires subject_type in {edge.subject_types}, got {triple.subject_type}"
    if triple.object_type not in edge.object_types:
        return f"{triple.relation} requires object_type in {edge.object_types}, got {triple.object_type}"
    return None
