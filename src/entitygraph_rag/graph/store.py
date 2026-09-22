"""GraphStore: the abstract interface pipeline/query code is written against.

Keeping every graph operation behind this interface is what makes the
backend choice (NetworkX now, Neo4j AuraDB later per the project plan) a
swappable implementation detail rather than something baked into the
extraction/resolution/retrieval code that consumes the graph.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable


class GraphStore(ABC):
    @abstractmethod
    def upsert_entity(self, entity: dict) -> None:
        """Insert or update a node, keyed on entity["entity_id"]."""

    @abstractmethod
    def upsert_edge(self, edge: dict) -> None:
        """Insert or merge an edge, keyed on (subject_id, relation, object_id).

        A second edge with the same key merges into the first rather than
        creating a parallel edge: its provenance is appended to the
        existing edge's provenance list, so a relation stated in multiple
        chunks yields one edge backed by multiple citations, not N
        duplicate edges.
        """

    def load(self, entities: Iterable[dict], edges: Iterable[dict]) -> None:
        """Bulk-load entities then edges via upsert_entity/upsert_edge."""
        for entity in entities:
            self.upsert_entity(entity)
        for edge in edges:
            self.upsert_edge(edge)

    @abstractmethod
    def get_entity(self, entity_id: str) -> dict | None:
        """Return the node's attributes, or None if entity_id isn't in the graph."""

    @abstractmethod
    def neighbors(self, entity_id: str, *, relation: str | None = None, direction: str = "out") -> list[dict]:
        """Return one dict per edge touching entity_id: entity_id, direction, relation, confidence, provenance.

        direction is "out" (entity_id is the edge's subject), "in" (object),
        or "both". relation, if given, filters to that edge type only.
        """

    @abstractmethod
    def node_count(self) -> int: ...

    @abstractmethod
    def edge_count(self) -> int: ...
