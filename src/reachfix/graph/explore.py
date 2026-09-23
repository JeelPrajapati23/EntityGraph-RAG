"""Ego-subgraph extraction for visualization, written only against the GraphStore interface.

Returns a flat {"nodes": [...], "edges": [...]} shape a frontend graph
library can render directly. Edges are keyed subject-first on
(subject_id, relation, object_id), so an edge reached from both of its
endpoints during the breadth-first walk still appears once.
"""

from .store import GraphStore


# Node properties the frontend shows (advisory severity and title, whether a version is a lockfile root).
DISPLAY_PROPERTIES = ("severity", "summary", "is_root")


def graph_node(store: GraphStore, entity_id: str) -> dict:
    entity = store.get_entity(entity_id) or {}
    properties = entity.get("properties") or {}
    node = {
        "entity_id": entity_id,
        "canonical_name": entity.get("canonical_name", entity_id),
        "entity_type": entity.get("entity_type"),
    }
    node.update({key: properties[key] for key in DISPLAY_PROPERTIES if properties.get(key) is not None})
    if cves := [a for a in entity.get("aliases", []) if a.startswith("CVE-")]:
        node["cves"] = cves
    return node


def ego_subgraph(store: GraphStore, entity_id: str, *, depth: int = 1, max_nodes: int = 200) -> dict:
    """Every node within `depth` hops of entity_id (either edge direction), plus the edges between them.

    Stops expanding once max_nodes nodes have been collected, so a hub
    entity can't return the whole graph. Returns empty lists if entity_id
    isn't in the graph.
    """
    if store.get_entity(entity_id) is None:
        return {"nodes": [], "edges": []}

    visited = {entity_id}
    frontier = [entity_id]
    edges: dict[tuple[str, str, str], dict] = {}

    for _ in range(depth):
        next_frontier = []
        for current in frontier:
            for neighbor in store.neighbors(current, direction="both"):
                other = neighbor["entity_id"]
                if other not in visited:
                    if len(visited) >= max_nodes:
                        continue
                    visited.add(other)
                    next_frontier.append(other)
                subject, obj = (current, other) if neighbor["direction"] == "out" else (other, current)
                edges[(subject, neighbor["relation"], obj)] = {
                    "source": subject,
                    "target": obj,
                    "relation": neighbor["relation"],
                    "confidence": neighbor["confidence"],
                    "n_citations": len(neighbor["provenance"]),
                }
        frontier = next_frontier

    return {"nodes": [graph_node(store, node_id) for node_id in sorted(visited)], "edges": list(edges.values())}
