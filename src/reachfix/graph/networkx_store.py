"""NetworkX-backed GraphStore — in-memory, persisted to a local pickle file.

No external account/credentials needed, so this is the default backend for
local development; the GraphStore interface means a Neo4j AuraDB backend
(the plan's portfolio-visible target) can be dropped in later without
touching any pipeline or query code written against GraphStore.

A MultiDiGraph, keyed per edge by relation name, is what gives upsert_edge
its merge behavior almost for free: a second SUPPLIES edge between the same
two nodes lands on the same (u, v, "SUPPLIES") slot instead of creating a
parallel edge.
"""

import pickle
from pathlib import Path

import networkx as nx

from .store import GraphStore

# Deterministic and derived edges (schema v2) carry no LLM confidence: they are ground truth.
DEFAULT_CONFIDENCE = 1.0
PROVENANCE_FIELDS = ("source_chunk_id", "source_doc_id", "source_url", "extraction_method", "confidence", "extracted_at")


def provenance_entry(edge: dict) -> dict:
    """The edge's provenance fields. Which ones are set varies by edge type (e.g. only llm edges have a chunk id)."""
    entry = {k: edge[k] for k in PROVENANCE_FIELDS if edge.get(k) is not None}
    entry.setdefault("confidence", DEFAULT_CONFIDENCE)
    return entry


class NetworkXGraphStore(GraphStore):
    def __init__(self) -> None:
        self._graph = nx.MultiDiGraph()

    def upsert_entity(self, entity: dict) -> None:
        entity_id = entity["entity_id"]
        if self._graph.has_node(entity_id):
            self._graph.nodes[entity_id].update(entity)
        else:
            self._graph.add_node(entity_id, **entity)

    def upsert_edge(self, edge: dict) -> None:
        subject_id = edge["subject_id"]
        object_id = edge["object_id"]
        relation = edge["relation"]
        confidence = edge.get("confidence", DEFAULT_CONFIDENCE)
        provenance = edge.get("provenance") or [provenance_entry(edge)]
        properties = edge.get("properties", {})

        if self._graph.has_edge(subject_id, object_id, key=relation):
            data = self._graph[subject_id][object_id][relation]
            data["provenance"].extend(provenance)
            data["confidence"] = max(data["confidence"], confidence)
            for key, value in properties.items():
                data["properties"].setdefault(key, value)  # the first source's properties win
        else:
            self._graph.add_edge(
                subject_id,
                object_id,
                key=relation,
                relation=relation,
                confidence=confidence,
                provenance=list(provenance),
                properties=dict(properties),
            )

    def get_entity(self, entity_id: str) -> dict | None:
        if not self._graph.has_node(entity_id):
            return None
        return dict(self._graph.nodes[entity_id])

    def neighbors(self, entity_id: str, *, relation: str | None = None, direction: str = "out") -> list[dict]:
        results = []
        if direction in ("out", "both"):
            for _, neighbor_id, key, data in self._graph.out_edges(entity_id, keys=True, data=True):
                if relation is not None and key != relation:
                    continue
                results.append({"entity_id": neighbor_id, "direction": "out", **data})
        if direction in ("in", "both"):
            for neighbor_id, _, key, data in self._graph.in_edges(entity_id, keys=True, data=True):
                if relation is not None and key != relation:
                    continue
                results.append({"entity_id": neighbor_id, "direction": "in", **data})
        return results

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def save_to_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self._graph, f)

    @classmethod
    def from_file(cls, path: Path) -> "NetworkXGraphStore":
        store = cls()
        with path.open("rb") as f:
            store._graph = pickle.load(f)
        return store
