"""A GraphStore that layers a small writable graph over a read-only base graph.

Used to query one uploaded lockfile against the corpus graph without
copying or mutating it: the upload's versions and DEPENDS_ON /
HAS_VULNERABILITY edges go into the overlay, and advisories, their ranges
and fixes come from the base. Writes only touch the overlay, so one base
can serve concurrent requests.

Where both layers have an edge between the same two nodes with the same
relation, the overlay's edge replaces the base's. That keeps a corpus
version's HAS_VULNERABILITY edges from appearing twice, and hides the
corpus lockfiles on a DEPENDS_ON edge the upload shares.
"""

from .networkx_store import NetworkXGraphStore
from .store import GraphStore


class OverlayGraphStore(GraphStore):
    def __init__(self, base: GraphStore, overlay: GraphStore | None = None) -> None:
        self.base = base
        self.overlay = overlay if overlay is not None else NetworkXGraphStore()

    def upsert_entity(self, entity: dict) -> None:
        self.overlay.upsert_entity(entity)

    def upsert_edge(self, edge: dict) -> None:
        self.overlay.upsert_edge(edge)

    def get_entity(self, entity_id: str) -> dict | None:
        # An overlay edge to a base node creates an attribute-less node in the overlay; that one doesn't count.
        found = self.overlay.get_entity(entity_id)
        if found and "entity_id" in found:
            return found
        return self.base.get_entity(entity_id) or found

    def neighbors(self, entity_id: str, *, relation: str | None = None, direction: str = "out") -> list[dict]:
        mine = self.overlay.neighbors(entity_id, relation=relation, direction=direction)
        shadowed = {(e["entity_id"], e["relation"], e["direction"]) for e in mine}
        theirs = [e for e in self.base.neighbors(entity_id, relation=relation, direction=direction)
                  if (e["entity_id"], e["relation"], e["direction"]) not in shadowed]
        return mine + theirs

    def node_count(self) -> int:
        """Upper bound: a node present in both layers is counted twice."""
        return self.base.node_count() + self.overlay.node_count()

    def edge_count(self) -> int:
        """Upper bound: an overlay edge replacing a base edge is counted twice."""
        return self.base.edge_count() + self.overlay.edge_count()
