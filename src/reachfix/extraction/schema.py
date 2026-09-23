"""Load a versioned entity/relation schema (schema/v2.yaml by default).

Everything LLM-facing is generated from the loaded schema rather than
hand-duplicated: the condition-extraction prompt and output model
(conditions/) and the router's pattern/relation Literals (depgraph/). A new
domain is a new schema version file, not a code change.
"""

from dataclasses import dataclass, field
from pathlib import Path
import yaml

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "schema" / "v2.yaml"


@dataclass
class NodeType:
    name: str
    description: str
    properties: list[str]
    # property -> {allowed value: description}; only for closed-vocabulary properties
    property_values: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class EdgeType:
    name: str
    subject_types: list[str]
    object_types: list[str]
    description: str
    symmetric: bool = False
    # deterministic / derived / llm. An edge that declares none is LLM-extracted.
    extraction: str = "llm"


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

    def llm_edge_types(self) -> dict[str, "EdgeType"]:
        """The edge types an LLM extracts. Only these belong in an extraction prompt or output model."""
        return {name: edge for name, edge in self.edge_types.items() if edge.extraction == "llm"}


def _as_list(value: str | list[str]) -> list[str]:
    return value if isinstance(value, list) else [value]


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> Schema:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    node_types = {
        name: NodeType(
            name=name,
            description=body["description"].strip(),
            properties=body.get("properties", []),
            property_values=body.get("property_values", {}),
        )
        for name, body in raw["node_types"].items()
    }
    edge_types = {
        name: EdgeType(
            name=name,
            subject_types=_as_list(body["subject"]),
            object_types=_as_list(body["object"]),
            description=body["description"].strip(),
            symmetric=body.get("symmetric", False),
            extraction=body.get("extraction", "llm"),
        )
        for name, body in raw["edge_types"].items()
    }

    return Schema(
        version=raw["version"],
        node_types=node_types,
        edge_types=edge_types,
        edge_properties=raw["edge_properties"],
    )
